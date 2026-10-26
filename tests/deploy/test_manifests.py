"""Render the Kustomize overlays and assert OpenShift restricted-v2 friendliness.

Run with the backend venv:  backend/.venv/bin/pytest tests/deploy
Needs one of: $KUSTOMIZE, `kustomize`, `oc`, or `kubectl` on PATH.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
OVERLAYS = ROOT / "deploy" / "kustomize" / "overlays"


def _kustomize_cmd() -> list[str] | None:
    if os.environ.get("KUSTOMIZE"):
        return [os.environ["KUSTOMIZE"], "build"]
    for tool, args in (("kustomize", ["build"]), ("oc", ["kustomize"]), ("kubectl", ["kustomize"])):
        if path := shutil.which(tool):
            return [path, *args]
    return None


CMD = _kustomize_cmd()
pytestmark = pytest.mark.skipif(CMD is None, reason="no kustomize/oc/kubectl available")


def render(overlay: str) -> list[dict[str, Any]]:
    assert CMD is not None
    out = subprocess.run([*CMD, str(OVERLAYS / overlay)], check=True, capture_output=True, text=True).stdout
    return [d for d in yaml.safe_load_all(out) if d]


def render_with_postgres(overlay: str, tmp_path: Path) -> list[dict[str, Any]]:
    """Render overlay + postgres component the way scripts/install.sh --with-postgres does."""
    assert CMD is not None
    wrapper = ROOT / "deploy" / "kustomize" / f".test-{tmp_path.name}"
    wrapper.mkdir()
    try:
        (wrapper / "kustomization.yaml").write_text(
            f"apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources: [../overlays/{overlay}]\ncomponents: [../components/postgres]\n"
        )
        out = subprocess.run([*CMD, str(wrapper)], check=True, capture_output=True, text=True).stdout
    finally:
        for f in wrapper.iterdir():
            f.unlink()
        wrapper.rmdir()
    return [d for d in yaml.safe_load_all(out) if d]


def by_kind(docs: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [d for d in docs if d["kind"] == kind]


@pytest.fixture(params=["openshift", "local"])
def docs(request: pytest.FixtureRequest) -> list[dict[str, Any]]:
    return render(request.param)


def test_no_hardcoded_namespace(docs: list[dict[str, Any]]) -> None:
    assert not by_kind(docs, "Namespace")
    assert all("namespace" not in d["metadata"] for d in docs)


def test_deployments_are_restricted_v2_compatible(docs: list[dict[str, Any]]) -> None:
    deployments = by_kind(docs, "Deployment")
    assert {d["metadata"]["name"] for d in deployments} == {"marketlab-backend", "marketlab-frontend"}
    check_restricted(deployments)


def check_restricted(deployments: list[dict[str, Any]], writable_root: frozenset[str] = frozenset()) -> None:
    for d in deployments:
        pod = d["spec"]["template"]["spec"]
        name = d["metadata"]["name"]
        assert pod["securityContext"]["runAsNonRoot"] is True, name
        assert pod["securityContext"]["seccompProfile"]["type"] == "RuntimeDefault", name
        assert "runAsUser" not in pod["securityContext"], f"{name}: let OpenShift assign the UID"
        assert pod.get("automountServiceAccountToken") is False, name
        for key in ("hostNetwork", "hostPID", "hostIPC"):
            assert not pod.get(key), f"{name}: {key}"
        assert all("hostPath" not in v for v in pod.get("volumes", [])), name
        for c in pod["containers"]:
            sc = c["securityContext"]
            assert sc["allowPrivilegeEscalation"] is False
            assert sc["capabilities"]["drop"] == ["ALL"]
            assert "add" not in sc["capabilities"]
            assert not sc.get("privileged")
            assert "runAsUser" not in sc
            if name not in writable_root:
                assert sc["readOnlyRootFilesystem"] is True
                assert any(m["mountPath"] == "/tmp" for m in c["volumeMounts"]), "writable /tmp required"
            for probe in ("startupProbe", "readinessProbe", "livenessProbe"):
                assert probe in c, f"{name}: missing {probe}"
            for kind in ("requests", "limits"):
                assert {"cpu", "memory"} <= set(c["resources"][kind]), f"{name}: {kind}"


def test_backend_is_single_replica_recreate(docs: list[dict[str, Any]]) -> None:
    (backend,) = [d for d in by_kind(docs, "Deployment") if d["metadata"]["name"] == "marketlab-backend"]
    assert backend["spec"]["replicas"] == 1
    assert backend["spec"]["strategy"]["type"] == "Recreate"


def test_selectors_match_services_and_templates(docs: list[dict[str, Any]]) -> None:
    deployments = {d["metadata"]["name"]: d for d in by_kind(docs, "Deployment")}
    for d in deployments.values():
        sel = d["spec"]["selector"]["matchLabels"]
        assert sel.items() <= d["spec"]["template"]["metadata"]["labels"].items()
    for svc in by_kind(docs, "Service"):
        assert svc["spec"]["type"] == "ClusterIP"
        target = deployments[svc["metadata"]["name"]]
        assert svc["spec"]["selector"].items() <= target["spec"]["template"]["metadata"]["labels"].items()
        port_names = {p["name"] for c in target["spec"]["template"]["spec"]["containers"] for p in c["ports"]}
        assert {p["targetPort"] for p in svc["spec"]["ports"]} <= port_names


def test_configmaps_referenced_exist(docs: list[dict[str, Any]]) -> None:
    cms = {d["metadata"]["name"] for d in by_kind(docs, "ConfigMap")}
    for d in by_kind(docs, "Deployment"):
        for c in d["spec"]["template"]["spec"]["containers"]:
            for ref in c.get("envFrom", []):
                assert ref["configMapRef"]["name"] in cms


def test_no_secrets_or_cluster_specific_values(docs: list[dict[str, Any]]) -> None:
    text = yaml.safe_dump_all(docs)
    assert not by_kind(docs, "Secret")
    for needle in ("apps.", ".svc.cluster.local", "password", "PASSWORD"):
        assert needle not in text


def test_route_only_in_openshift_overlay() -> None:
    os_docs, local_docs = render("openshift"), render("local")
    (route,) = by_kind(os_docs, "Route")
    assert "host" not in route["spec"], "host must be generated by the target cluster"
    assert route["spec"]["to"]["name"] == "marketlab-frontend"
    assert route["spec"]["tls"]["termination"] == "edge"
    assert "haproxy.router.openshift.io/timeout" in route["metadata"]["annotations"]
    assert not by_kind(local_docs, "Route")


def test_image_references_are_pinned_published_images() -> None:
    """Both overlays deploy the published images, pinned by digest (single source: components/images)."""
    comp = yaml.safe_load((ROOT / "deploy" / "kustomize" / "components" / "images" / "kustomization.yaml").read_text())
    pinned = {i["name"]: f'{i["newName"]}@{i["digest"]}' for i in comp["images"]}
    assert set(pinned) == {"marketlab-backend", "marketlab-frontend"}
    for overlay in ("local", "openshift"):
        images = {
            c["name"]: c["image"]
            for d in by_kind(render(overlay), "Deployment") for c in d["spec"]["template"]["spec"]["containers"]
        }
        assert images == {"backend": pinned["marketlab-backend"], "frontend": pinned["marketlab-frontend"]}, overlay
        assert all("@sha256:" in i and len(i.split("@sha256:")[1]) == 64 for i in images.values())


def test_backend_only_reachable_from_frontend(docs: list[dict[str, Any]]) -> None:
    (np,) = [n for n in by_kind(docs, "NetworkPolicy") if n["metadata"]["name"] == "marketlab-backend-ingress"]
    peers = np["spec"]["ingress"][0]["from"]
    assert peers == [{"podSelector": {"matchLabels": {"app.kubernetes.io/name": "marketlab", "app.kubernetes.io/component": "frontend"}}}]


@pytest.mark.parametrize("overlay", ["openshift", "local"])
def test_postgres_component(overlay: str, tmp_path: Path) -> None:
    docs = render_with_postgres(overlay, tmp_path)
    deps = {d["metadata"]["name"]: d for d in by_kind(docs, "Deployment")}
    assert set(deps) == {"marketlab-backend", "marketlab-frontend", "marketlab-postgres"}
    # The sclorg image writes outside its data volume, so only the database is exempt from read-only root.
    check_restricted(list(deps.values()), writable_root=frozenset({"marketlab-postgres"}))
    pg = deps["marketlab-postgres"]
    assert pg["spec"]["strategy"]["type"] == "Recreate" and pg["spec"]["replicas"] == 1
    assert pg["spec"]["template"]["spec"]["containers"][0]["image"].startswith("quay.io/sclorg/postgresql-16")
    assert not by_kind(docs, "Secret"), "the DB secret must be created at install time, never committed"
    (pvc,) = by_kind(docs, "PersistentVolumeClaim")
    assert pvc["metadata"]["name"] == "marketlab-postgres"
    svc = next(s for s in by_kind(docs, "Service") if s["metadata"]["name"] == "marketlab-postgres")
    assert svc["spec"]["type"] == "ClusterIP"
    env = {e["name"]: e for e in deps["marketlab-backend"]["spec"]["template"]["spec"]["containers"][0]["env"]}
    assert env["MARKETLAB_DB_PASSWORD"]["valueFrom"]["secretKeyRef"] == {"name": "marketlab-db", "key": "POSTGRESQL_PASSWORD"}
    cm = next(c for c in by_kind(docs, "ConfigMap") if c["metadata"]["name"] == "marketlab-backend-config")
    assert cm["data"]["MARKETLAB_PERSISTENCE_MODE"] == "postgres"
    np = next(n for n in by_kind(docs, "NetworkPolicy") if n["metadata"]["name"] == "marketlab-postgres-ingress")
    assert np["spec"]["ingress"][0]["from"][0]["podSelector"]["matchLabels"]["app.kubernetes.io/component"] == "backend"


@pytest.mark.parametrize("overlay", ["openshift", "local"])
def test_every_resource_is_labelled_for_uninstall(overlay: str, tmp_path: Path) -> None:
    for d in render(overlay) + render_with_postgres(overlay, tmp_path):
        assert d["metadata"].get("labels", {}).get("app.kubernetes.io/part-of") == "marketlab", f'{d["kind"]}/{d["metadata"]["name"]}'


def test_install_image_overrides_target_the_right_containers(tmp_path: Path) -> None:
    """scripts/lib.sh override_images must replace each container's own image (keys are emitted alphabetically)."""
    docs = render_with_postgres("openshift", tmp_path)
    f = tmp_path / "rendered.yaml"
    f.write_text(yaml.safe_dump_all(docs, sort_keys=True))
    digest = "sha256:" + "b" * 64
    subprocess.run(
        ["bash", "-c", f'source "{ROOT}/scripts/lib.sh" && override_images "$1" backend=r/be:1 frontend=r/fe@{digest} postgres=r/pg:16 && override_images "$1" frontend=',
         "_", str(f)],
        check=True,
    )
    images = {c["name"]: c["image"] for d in yaml.safe_load_all(f.read_text()) if d and d["kind"] == "Deployment"
              for c in d["spec"]["template"]["spec"]["containers"]}
    assert images == {"backend": "r/be:1", "frontend": f"r/fe@{digest}", "postgres": "r/pg:16"}

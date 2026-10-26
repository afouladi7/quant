import { Link, useParams } from "react-router-dom";
import { Quiz } from "../components/learn";
import { Panel } from "../components/ui";
import { LESSONS, LEVELS, type Lesson } from "../learn/lessons";
import { useProgress } from "../learn/progress";

export function Learn() {
  const { lessonId } = useParams();
  const lesson = LESSONS.find((l) => l.id === lessonId);
  return lesson ? <LessonView lesson={lesson} /> : <LessonList />;
}

function LessonList() {
  const { done } = useProgress();
  return (
    <div className="page">
      <header>
        <h1>Learning path</h1>
        <p className="lead">
          Short lessons, each with a hands-on exercise in the app and a quick quiz. Start at the beginning or jump to your level.
          Progress is saved in this browser.
        </p>
        <div className="meter" aria-label={`${done.size} of ${LESSONS.length} lessons complete`}>
          <div className="meter-label small"><span>Progress</span><span>{done.size} / {LESSONS.length}</span></div>
          <div className="meter-track"><div className="meter-fill" style={{ width: `${(done.size / LESSONS.length) * 100}%` }} /></div>
        </div>
      </header>
      {([1, 2, 3] as const).map((lvl) => (
        <Panel key={lvl} title={LEVELS[lvl].name} id={`lvl-${lvl}`} actions={<span className="small muted">{LEVELS[lvl].who}</span>}>
          <ol className="lesson-list">
            {LESSONS.filter((l) => l.level === lvl).map((l) => (
              <li key={l.id}>
                <Link to={`/learn/${l.id}`} className="lesson-link">
                  <span className="lesson-check" aria-label={done.has(l.id) ? "completed" : "not started"}>{done.has(l.id) ? "✓" : "○"}</span>
                  <span>
                    <b>{l.title}</b>
                    <span className="small muted"> · {l.minutes} min</span>
                    <span className="lesson-summary small">{l.summary}</span>
                  </span>
                </Link>
              </li>
            ))}
          </ol>
        </Panel>
      ))}
    </div>
  );
}

function LessonView({ lesson }: { lesson: Lesson }) {
  const { done, mark } = useProgress();
  const idx = LESSONS.indexOf(lesson);
  const prev = LESSONS[idx - 1];
  const next = LESSONS[idx + 1];
  return (
    <div className="page lesson">
      <nav className="small" aria-label="Breadcrumb"><Link to="/learn">Learning path</Link> › {LEVELS[lesson.level].name}</nav>
      <header>
        <h1>{lesson.title}</h1>
        <p className="lead">{lesson.summary}</p>
        <p className="small muted">About {lesson.minutes} minutes · lesson {idx + 1} of {LESSONS.length}</p>
      </header>
      <Panel title="The idea" id="idea">
        {lesson.body.map((p) => <p key={p}>{p}</p>)}
      </Panel>
      <div className="grid-2">
        <Panel title="Key ideas" id="key">
          <ul className="key-ideas">{lesson.keyIdeas.map((k) => <li key={k}>{k}</li>)}</ul>
          {lesson.formula && (<><h3 className="sub">Formula</h3><pre className="formula">{lesson.formula}</pre></>)}
        </Panel>
        <Panel title="Try it yourself" id="try">
          <ol>{lesson.tryIt.steps.map((s) => <li key={s}>{s}</li>)}</ol>
          <Link to={lesson.tryIt.to} className="btn primary">{lesson.tryIt.label} →</Link>
        </Panel>
      </div>
      <Panel title="Check your understanding" id="quiz">
        <Quiz key={lesson.id} questions={lesson.quiz} onComplete={(score) => score === lesson.quiz.length && mark(lesson.id)} />
        <p className="small muted">
          {done.has(lesson.id) ? "✓ Lesson complete." : "Answer every question correctly to mark this lesson complete, or "}
          {!done.has(lesson.id) && <button type="button" className="link" onClick={() => mark(lesson.id)}>mark it complete now</button>}
        </p>
      </Panel>
      <nav className="lesson-nav" aria-label="Lesson navigation">
        {prev ? <Link to={`/learn/${prev.id}`} className="btn">← {prev.title}</Link> : <span />}
        {next ? <Link to={`/learn/${next.id}`} className="btn primary">{next.title} →</Link> : <Link to="/learn" className="btn">Back to all lessons</Link>}
      </nav>
    </div>
  );
}

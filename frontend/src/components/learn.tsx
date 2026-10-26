import { useId, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { GLOSSARY } from "../learn/glossary";
import type { QuizQuestion } from "../learn/lessons";

/** A glossary term: dotted underline, definition on hover or keyboard focus, link to the glossary. */
export function Term({ id, children }: { id: string; children?: ReactNode }) {
  const entry = GLOSSARY[id];
  const tipId = useId();
  if (!entry) return <>{children}</>;
  return (
    <span className="term">
      <button type="button" className="term-btn" aria-describedby={tipId}>{children ?? entry.term}</button>
      <span role="tooltip" id={tipId} className="term-tip">
        <b>{entry.term}</b>
        <span>{entry.simple}</span>
        {entry.technical && <span className="term-tech">{entry.technical}</span>}
        <Link to={`/glossary#${id}`} className="term-link">Glossary →</Link>
      </span>
    </span>
  );
}

/** "What am I looking at?" toggle used in panel headers. */
export function HelpToggle({ children, label = "What am I looking at?" }: { children: ReactNode; label?: string }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <>
      <button type="button" className="help-btn" aria-expanded={open} aria-controls={id} onClick={() => setOpen(!open)} title={label}>
        <span aria-hidden="true">?</span><span className="sr-only">{label}</span>
      </button>
      {open && <div id={id} className="help-box" role="note">{children}</div>}
    </>
  );
}

/** Short "start here" box shown at the top of a page. */
export function StartHere({ title = "Start here", steps, children }: { title?: string; steps: ReactNode[]; children?: ReactNode }) {
  return (
    <section className="start-here" aria-label={title}>
      <h2>{title}</h2>
      {children}
      <ol>{steps.map((s, i) => <li key={i}>{s}</li>)}</ol>
    </section>
  );
}

export function Quiz({ questions, onComplete }: { questions: QuizQuestion[]; onComplete?: (score: number) => void }) {
  const [picked, setPicked] = useState<(number | null)[]>(questions.map(() => null));
  const done = picked.every((p) => p !== null);
  const score = picked.filter((p, i) => p === questions[i].answer).length;
  const choose = (qi: number, oi: number) => {
    if (picked[qi] !== null) return;
    const next = picked.map((p, i) => (i === qi ? oi : p));
    setPicked(next);
    if (next.every((p) => p !== null)) onComplete?.(next.filter((p, i) => p === questions[i].answer).length);
  };
  return (
    <div className="quiz">
      {questions.map((q, qi) => (
        <fieldset key={q.q} className="quiz-q">
          <legend>{qi + 1}. {q.q}</legend>
          <div className="quiz-options">
            {q.options.map((o, oi) => {
              const chosen = picked[qi] === oi;
              const state = picked[qi] === null ? "" : oi === q.answer ? "right" : chosen ? "wrong" : "";
              return (
                <button key={o} type="button" className={`quiz-opt ${state}`} aria-pressed={chosen} disabled={picked[qi] !== null} onClick={() => choose(qi, oi)}>
                  {state === "right" && <span aria-hidden="true">✓ </span>}{state === "wrong" && <span aria-hidden="true">✕ </span>}{o}
                </button>
              );
            })}
          </div>
          {picked[qi] !== null && (
            <p className={`quiz-why ${picked[qi] === q.answer ? "right" : "wrong"}`} role="status">
              {picked[qi] === q.answer ? "Correct. " : "Not quite. "}{q.why}
            </p>
          )}
        </fieldset>
      ))}
      {done && <p className="quiz-score" role="status">Score: {score} / {questions.length}</p>}
      {done && <button type="button" className="link" onClick={() => setPicked(questions.map(() => null))}>Try again</button>}
    </div>
  );
}

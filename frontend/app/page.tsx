"use client";

import { ChangeEvent, FormEvent, useEffect, useMemo, useRef, useState } from "react";

type Student = { id: number; display_name: string; grade: number | null; preferred_language: string };
type Mastery = { skill_code: string; probability: number; exposures: number; correct_streak: number };
type TutorState =
  | "diagnose"
  | "ask_attempt"
  | "hint_1"
  | "hint_2"
  | "explain_step"
  | "verify"
  | "transfer"
  | "complete";

type TutorTurn = {
  message: string;
  state: TutorState;
  next_action: string;
  hint_level: number;
  skill_tags: string[];
  misconception: string | null;
  likely_correct: boolean | null;
  reveal_final_answer: boolean;
};

type ChatMessage =
  | { role: "student"; content: string }
  | { role: "tutor"; content: string; turn: TutorTurn };

type StartResponse = {
  session_id: number;
  analysis: {
    normalized_problem: string;
    subject: string;
    skills: string[];
    confidence: number;
  };
  tutor: TutorTurn;
};

type NextLearningAction = {
  question_id: string;
  skill_code: string;
  problem_text: string;
  difficulty: number;
};

type TutorReplyResponse = {
  tutor: TutorTurn;
  next_learning_action?: NextLearningAction | null;
};

type StartAuthoredResponse = {
  session_id: number;
  question: NextLearningAction;
  tutor: TutorTurn;
};

type PilotPhase = "pre" | "intervention" | "post" | "complete";

type PilotStatus = {
  pilot_id: string;
  phase: PilotPhase;
  skills_total: number;
  pre_completed_skills: number;
  learning_completed_skills: number;
  post_completed_skills: number;
};

type PilotAssessmentItem = {
  phase: "pre" | "post";
  question_id: string;
  skill_code: string;
  problem_text: string;
  difficulty: number;
};

class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = "ApiError";
  }
}

type TutorReplyIntent = "attempt" | "hint_request";

const TUTOR_STATE_LABELS: Record<TutorState, string> = {
  diagnose: "Đang chẩn đoán",
  ask_attempt: "Đang chờ em thử",
  hint_1: "Gợi ý 1",
  hint_2: "Gợi ý 2",
  explain_step: "Giải thích bước",
  verify: "Đang kiểm tra",
  transfer: "Bài vận dụng",
  complete: "Hoàn thành",
};

const HINT_ELIGIBLE_STATES: ReadonlySet<TutorState> = new Set<TutorState>([
  "ask_attempt",
  "hint_1",
  "hint_2",
]);

const HINT_REQUEST_MESSAGE = "Em muốn xin thêm một gợi ý.";

const API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1";

async function api<T>(path: string, options: RequestInit = {}, token?: string): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${API}${path}`, { ...options, headers });
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      message = body.detail || message;
    } catch {}
    throw new ApiError(message, response.status);
  }
  if (response.status === 204) return undefined as T;
  return response.json();
}

async function fetchPilotPresentation(
  studentId: number,
  token: string,
): Promise<{
  status: PilotStatus | null;
  assessment: PilotAssessmentItem | null;
  noEnrollment: boolean;
}> {
  let status: PilotStatus;
  try {
    status = await api<PilotStatus>(`/students/${studentId}/pilot`, {}, token);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      return { status: null, assessment: null, noEnrollment: true };
    }
    throw error;
  }
  if (status.phase !== "pre" && status.phase !== "post") {
    return { status, assessment: null, noEnrollment: false };
  }
  const assessment = await api<PilotAssessmentItem>(
    `/students/${studentId}/pilot/assessment`,
    {},
    token,
  );
  return { status, assessment, noEnrollment: false };
}

export default function Home() {
  const [token, setToken] = useState("");
  const [email, setEmail] = useState("demo@example.com");
  const [password, setPassword] = useState("demo-pass-123");
  const [students, setStudents] = useState<Student[]>([]);
  const [studentName, setStudentName] = useState("Học sinh 1");
  const [grade, setGrade] = useState(8);
  const [selectedStudent, setSelectedStudent] = useState<number | null>(null);
  const [mastery, setMastery] = useState<Mastery[]>([]);
  const [problem, setProblem] = useState("2x + 3 = 11. Hãy tìm x.");
  const [imageDataUrl, setImageDataUrl] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<number | null>(null);
  const [sessionStudentId, setSessionStudentId] = useState<number | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [reply, setReply] = useState("");
  const [analysis, setAnalysis] = useState<StartResponse["analysis"] | null>(null);
  const [nextLearningAction, setNextLearningAction] = useState<NextLearningAction | null>(null);
  const [authoredQuestion, setAuthoredQuestion] = useState<NextLearningAction | null>(null);
  const [pilotStatus, setPilotStatus] = useState<PilotStatus | null>(null);
  const [pilotAssessment, setPilotAssessment] = useState<PilotAssessmentItem | null>(null);
  const [pilotCandidate, setPilotCandidate] = useState("");
  const [pilotSessionStudentId, setPilotSessionStudentId] = useState<number | null>(null);
  const [pilotNotEnrolled, setPilotNotEnrolled] = useState(false);
  const [pilotLoading, setPilotLoading] = useState(false);
  const [pilotError, setPilotError] = useState("");
  const [pilotNotice, setPilotNotice] = useState("");
  const [pilotReloadVersion, setPilotReloadVersion] = useState(0);
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const tutorRequestInFlight = useRef(false);
  const pilotRequestVersion = useRef(0);
  const selectedStudentRef = useRef<number | null>(null);

  useEffect(() => {
    const stored = localStorage.getItem("aitutor_token") || "";
    if (stored) setToken(stored);
  }, []);

  useEffect(() => {
    if (token) void refreshStudents();
  }, [token]);

  useEffect(() => {
    if (selectedStudent && token) void refreshMastery(selectedStudent);
  }, [selectedStudent, token]);

  useEffect(() => {
    const studentId = selectedStudent;
    const requestToken = token;
    const requestVersion = ++pilotRequestVersion.current;
    let cancelled = false;
    const isCurrentRequest = () =>
      !cancelled &&
      requestVersion === pilotRequestVersion.current &&
      selectedStudentRef.current === studentId;

    if (studentId === null || !requestToken) {
      setPilotStatus(null);
      setPilotAssessment(null);
      setPilotCandidate("");
      setPilotNotEnrolled(false);
      setPilotLoading(false);
      setPilotError("");
      return () => {
        cancelled = true;
      };
    }

    setPilotLoading(true);
    setPilotError("");
    void (async () => {
      try {
        const presentation = await fetchPilotPresentation(studentId, requestToken);
        if (!isCurrentRequest()) return;
        setPilotStatus(presentation.status);
        setPilotAssessment(presentation.assessment);
        setPilotNotEnrolled(presentation.noEnrollment);
      } catch (error) {
        if (!isCurrentRequest()) return;
        setPilotError(error instanceof Error ? error.message : "Không tải được trạng thái pilot");
      } finally {
        if (isCurrentRequest()) setPilotLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [selectedStudent, token, pilotReloadVersion]);

  const currentStudent = useMemo(
    () => students.find((s) => s.id === selectedStudent) || null,
    [students, selectedStudent]
  );

  const latestTutorTurn = useMemo(() => {
    for (let index = messages.length - 1; index >= 0; index -= 1) {
      const message = messages[index];
      if (message.role === "tutor") return message.turn;
    }
    return null;
  }, [messages]);

  const canRequestHint =
    latestTutorTurn !== null && HINT_ELIGIBLE_STATES.has(latestTutorTurn.state);

  function clearPilotPresentation() {
    setPilotStatus(null);
    setPilotAssessment(null);
    setPilotCandidate("");
    setPilotNotEnrolled(false);
    setPilotError("");
    setPilotNotice("");
    setPilotLoading(false);
  }

  function selectStudent(studentId: number | null) {
    selectedStudentRef.current = studentId;
    pilotRequestVersion.current += 1;
    setSelectedStudent(studentId);
    clearPilotPresentation();
  }

  async function authenticate(mode: "register" | "login") {
    setBusy(true);
    setStatus("");
    try {
      const result = await api<{ access_token: string }>(`/auth/${mode}`, {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      localStorage.setItem("aitutor_token", result.access_token);
      setToken(result.access_token);
      setStatus(mode === "register" ? "Đã tạo tài khoản." : "Đăng nhập thành công.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Có lỗi xảy ra");
    } finally {
      setBusy(false);
    }
  }

  async function refreshStudents() {
    try {
      const data = await api<Student[]>("/students", {}, token);
      setStudents(data);
      if (!selectedStudent && data.length) selectStudent(data[0].id);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Không tải được học sinh");
    }
  }

  async function createStudent(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      const student = await api<Student>("/students", {
        method: "POST",
        body: JSON.stringify({ display_name: studentName, grade, preferred_language: "vi" }),
      }, token);
      await refreshStudents();
      selectStudent(student.id);
      setStatus("Đã tạo hồ sơ học sinh.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Không tạo được học sinh");
    } finally {
      setBusy(false);
    }
  }

  async function refreshMastery(studentId: number) {
    try {
      setMastery(await api<Mastery[]>(`/students/${studentId}/mastery`, {}, token));
    } catch {
      setMastery([]);
    }
  }

  function chooseImage(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) {
      setStatus("Ảnh tối đa 5 MB trong bản MVP.");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => setImageDataUrl(String(reader.result));
    reader.readAsDataURL(file);
  }

  async function startTutor() {
    const studentId = selectedStudent;
    if (!studentId) {
      setStatus("Hãy tạo/chọn một học sinh trước.");
      return;
    }
    setBusy(true);
    setStatus("Đang phân tích bài...");
    try {
      const data = await api<StartResponse>("/tutor/start", {
        method: "POST",
        body: JSON.stringify({ student_id: studentId, problem_text: problem, image_data_url: imageDataUrl }),
      }, token);
      setSessionId(data.session_id);
      setSessionStudentId(studentId);
      setPilotSessionStudentId(null);
      setAnalysis(data.analysis);
      setMessages([{ role: "tutor", content: data.tutor.message, turn: data.tutor }]);
      setNextLearningAction(null);
      setAuthoredQuestion(null);
      setReply("");
      setStatus("Phiên học đã bắt đầu.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Không bắt đầu được phiên học");
    } finally {
      setBusy(false);
    }
  }

  async function startAuthoredTutor() {
    const recommendation = nextLearningAction;
    const studentId = sessionStudentId;
    if (studentId === null) {
      setStatus("Hãy tạo/chọn một học sinh trước.");
      return;
    }
    if (!recommendation || busy) return;

    setBusy(true);
    setStatus("Đang bắt đầu bài được chọn...");
    try {
      const data = await api<StartAuthoredResponse>("/tutor/start-authored", {
        method: "POST",
        body: JSON.stringify({
          student_id: studentId,
          question_id: recommendation.question_id,
        }),
      }, token);
      setSessionId(data.session_id);
      setSessionStudentId(studentId);
      setPilotSessionStudentId(null);
      setMessages([{ role: "tutor", content: data.tutor.message, turn: data.tutor }]);
      setAuthoredQuestion(data.question);
      setNextLearningAction(null);
      setReply("");
      setAnalysis(null);
      setImageDataUrl(null);
      setStatus("Bài học mới đã bắt đầu.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Không bắt đầu được bài được chọn");
    } finally {
      setBusy(false);
    }
  }

  async function submitTutorReply(studentText: string, intent: TutorReplyIntent) {
    const trimmedText = studentText.trim();
    if (!sessionId || busy || tutorRequestInFlight.current || !trimmedText) return;

    const replyPilotStudentId = pilotSessionStudentId;
    const isPilotReply =
      replyPilotStudentId !== null && sessionStudentId === replyPilotStudentId;

    tutorRequestInFlight.current = true;
    if (intent === "attempt") setReply("");
    setMessages((m) => [...m, { role: "student", content: trimmedText }]);
    setBusy(true);
    try {
      const data = await api<TutorReplyResponse>("/tutor/reply", {
        method: "POST",
        body: JSON.stringify({
          session_id: sessionId,
          student_message: trimmedText,
          intent,
        }),
      }, token);
      setMessages((m) => [
        ...m,
        { role: "tutor", content: data.tutor.message, turn: data.tutor },
      ]);
      if (isPilotReply) {
        setNextLearningAction(null);
        if (
          data.tutor.state === "complete" &&
          selectedStudentRef.current === replyPilotStudentId
        ) {
          setPilotReloadVersion((version) => version + 1);
        }
      } else {
        setNextLearningAction(data.next_learning_action ?? null);
      }
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Không gửi được câu trả lời");
    } finally {
      tutorRequestInFlight.current = false;
      setBusy(false);
    }
  }

  function sendReply(event: FormEvent) {
    event.preventDefault();
    void submitTutorReply(reply, "attempt");
  }

  function logout() {
    localStorage.removeItem("aitutor_token");
    setToken("");
    setStudents([]);
    selectStudent(null);
    setSessionId(null);
    setSessionStudentId(null);
    setPilotSessionStudentId(null);
    setMessages([]);
    setNextLearningAction(null);
    setAuthoredQuestion(null);
  }

  async function enrollPilot() {
    const studentId = selectedStudent;
    if (studentId === null || busy) return;
    setBusy(true);
    setPilotError("");
    setPilotNotice("");
    try {
      const data = await api<PilotStatus>(`/students/${studentId}/pilot`, {
        method: "POST",
      }, token);
      if (selectedStudentRef.current !== studentId) return;
      setPilotStatus(data);
      setPilotAssessment(null);
      setPilotCandidate("");
      setPilotNotEnrolled(false);
      setPilotReloadVersion((version) => version + 1);
    } catch (error) {
      if (selectedStudentRef.current === studentId) {
        setPilotError(error instanceof Error ? error.message : "Không thể bắt đầu luồng pilot");
      }
    } finally {
      setBusy(false);
    }
  }

  async function submitPilotAssessment(event: FormEvent) {
    event.preventDefault();
    const studentId = selectedStudent;
    const assessment = pilotAssessment;
    const candidate = pilotCandidate;
    if (studentId === null || !assessment || busy) return;

    setBusy(true);
    setPilotError("");
    setPilotNotice("");
    try {
      await api<void>(`/students/${studentId}/pilot/assessment`, {
        method: "POST",
        body: JSON.stringify({
          question_id: assessment.question_id,
          candidate,
        }),
      }, token);
      if (selectedStudentRef.current !== studentId) return;
      setPilotCandidate("");
      setPilotAssessment(null);
      setPilotNotice("Đã ghi nhận câu trả lời.");
      setPilotReloadVersion((version) => version + 1);
    } catch (error) {
      if (selectedStudentRef.current === studentId) {
        setPilotError(error instanceof Error ? error.message : "Không gửi được câu trả lời");
      }
    } finally {
      setBusy(false);
    }
  }

  async function startPilotLearning() {
    const studentId = selectedStudent;
    if (studentId === null || busy) return;
    if (pilotSessionStudentId === studentId && latestTutorTurn?.state !== "complete") return;

    setBusy(true);
    setPilotError("");
    setPilotNotice("");
    try {
      const data = await api<StartAuthoredResponse>(
        `/tutor/start-pilot-learning/${studentId}`,
        { method: "POST" },
        token,
      );
      if (selectedStudentRef.current !== studentId) return;
      setSessionId(data.session_id);
      setSessionStudentId(studentId);
      setPilotSessionStudentId(studentId);
      setMessages([{ role: "tutor", content: data.tutor.message, turn: data.tutor }]);
      setAuthoredQuestion(data.question);
      setAnalysis(null);
      setReply("");
      setNextLearningAction(null);
      setImageDataUrl(null);
      setStatus("Bài pilot đã bắt đầu.");
    } catch (error) {
      if (selectedStudentRef.current === studentId) {
        setPilotError(error instanceof Error ? error.message : "Không thể bắt đầu bài pilot");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <main>
      <header className="hero">
        <div>
          <p className="eyebrow">AI TUTOR VN · MVP</p>
          <h1>Gia sư AI ưu tiên học thật, không chỉ đưa đáp án.</h1>
          <p className="lede">Ảnh đề → chẩn đoán kỹ năng → hỏi gợi mở → ghi nhận sai lầm → cập nhật mức độ thành thạo.</p>
        </div>
        {token && <button className="ghost" onClick={logout}>Đăng xuất</button>}
      </header>

      {(status || busy) && (
        <div className="status" role="status" aria-live="polite">
          {busy ? "Đang xử lý..." : status}
        </div>
      )}

      {!token ? (
        <section className="card auth">
          <h2>1. Đăng nhập thử nghiệm</h2>
          <label>Email<input value={email} onChange={(e) => setEmail(e.target.value)} /></label>
          <label>Mật khẩu<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} /></label>
          <div className="row">
            <button disabled={busy} onClick={() => authenticate("register")}>Tạo tài khoản</button>
            <button className="secondary" disabled={busy} onClick={() => authenticate("login")}>Đăng nhập</button>
          </div>
        </section>
      ) : (
        <div className="grid">
          <aside>
            <section className="card">
              <h2>Học sinh</h2>
              <form onSubmit={createStudent} className="stack">
                <input value={studentName} onChange={(e) => setStudentName(e.target.value)} placeholder="Tên hiển thị" />
                <input type="number" min={1} max={12} value={grade} onChange={(e) => setGrade(Number(e.target.value))} />
                <button disabled={busy}>+ Tạo hồ sơ</button>
              </form>
              <div className="studentList">
                {students.map((student) => (
                  <button key={student.id} className={student.id === selectedStudent ? "student active" : "student"} onClick={() => selectStudent(student.id)}>
                    <span>{student.display_name}</span><small>Lớp {student.grade ?? "?"}</small>
                  </button>
                ))}
              </div>
            </section>

            <section className="card">
              <h2>Pilot</h2>
              {selectedStudent === null ? (
                <p className="muted">Hãy chọn học sinh để xem luồng pilot.</p>
              ) : pilotLoading && !pilotStatus && !pilotNotEnrolled ? (
                <p className="muted">Đang tải trạng thái pilot...</p>
              ) : pilotNotEnrolled ? (
                <div className="stack">
                  <p className="muted">Học sinh chưa tham gia luồng pilot.</p>
                  <button type="button" disabled={busy} onClick={() => void enrollPilot()}>
                    Bắt đầu luồng pilot
                  </button>
                </div>
              ) : pilotStatus ? (
                <div className="stack">
                  <div className="analysis">
                    <strong>Giai đoạn: {{
                      pre: "PRE",
                      intervention: "Học",
                      post: "POST",
                      complete: "Hoàn thành",
                    }[pilotStatus.phase]}</strong>
                    <span>PRE: {pilotStatus.pre_completed_skills} / {pilotStatus.skills_total}</span>
                    <span>Học: {pilotStatus.learning_completed_skills} / {pilotStatus.skills_total}</span>
                    <span>POST: {pilotStatus.post_completed_skills} / {pilotStatus.skills_total}</span>
                  </div>
                  {(pilotStatus.phase === "pre" || pilotStatus.phase === "post") && pilotAssessment && (
                    <>
                      <div className="analysis">
                        <strong>{pilotAssessment.problem_text}</strong>
                        <span>Kỹ năng: {pilotAssessment.skill_code}</span>
                        <span>Độ khó: {pilotAssessment.difficulty}</span>
                      </div>
                      <form onSubmit={submitPilotAssessment} className="stack">
                        <label>
                          Câu trả lời của em
                          <input
                            value={pilotCandidate}
                            onChange={(event) => setPilotCandidate(event.target.value)}
                            disabled={busy}
                          />
                        </label>
                        <button type="submit" disabled={busy || !pilotCandidate.trim()}>
                          Gửi câu trả lời
                        </button>
                      </form>
                    </>
                  )}
                  {pilotStatus.phase === "intervention" && (
                    <div className="stack">
                      <p className="muted">Hãy hoàn thành bài học pilot tiếp theo.</p>
                      {pilotSessionStudentId === selectedStudent && latestTutorTurn?.state !== "complete" ? (
                        <button type="button" disabled>Bài pilot đang được thực hiện</button>
                      ) : (
                        <button type="button" disabled={busy} onClick={() => void startPilotLearning()}>
                          Bắt đầu bài pilot tiếp theo
                        </button>
                      )}
                    </div>
                  )}
                  {pilotStatus.phase === "complete" && (
                    <p className="muted">Luồng pilot đã hoàn thành.</p>
                  )}
                </div>
              ) : null}
              {pilotAssessment === null && pilotLoading && pilotStatus &&
                (pilotStatus.phase === "pre" || pilotStatus.phase === "post") && (
                  <p className="muted">Đang tải câu hỏi hiện tại...</p>
                )}
              {pilotNotice && <p className="muted" role="status">{pilotNotice}</p>}
              {pilotError && (
                <div className="stack">
                  <p role="alert">{pilotError}</p>
                  <button type="button" className="secondary" disabled={busy || pilotLoading} onClick={() => setPilotReloadVersion((version) => version + 1)}>
                    Thử tải lại
                  </button>
                </div>
              )}
            </section>

            <section className="card">
              <h2>Mastery {currentStudent ? `· ${currentStudent.display_name}` : ""}</h2>
              {mastery.length === 0 ? <p className="muted">Chưa có dữ liệu attempt.</p> : mastery.map((item) => (
                <div key={item.skill_code} className="mastery">
                  <div><strong>{item.skill_code}</strong><span>{Math.round(item.probability * 100)}%</span></div>
                  <progress value={item.probability} max={1} />
                  <small>{item.exposures} lần luyện · streak {item.correct_streak}</small>
                </div>
              ))}
            </section>
          </aside>

          <section className="card tutor">
            <h2>Gia sư</h2>
            {!sessionId ? (
              <div className="stack">
                <label>Nhập đề bài<textarea value={problem} onChange={(e) => setProblem(e.target.value)} rows={5} /></label>
                <label>Hoặc thêm ảnh đề<input type="file" accept="image/*" onChange={chooseImage} /></label>
                {imageDataUrl && <img className="preview" src={imageDataUrl} alt="Ảnh đề đã chọn" />}
                <button disabled={busy || !selectedStudent} onClick={startTutor}>Phân tích & bắt đầu học</button>
              </div>
            ) : (
              <>
                {authoredQuestion && (
                  <div className="analysis">
                    <strong>{authoredQuestion.problem_text}</strong>
                    <span>Kỹ năng: {authoredQuestion.skill_code}</span>
                    <span>Độ khó: {authoredQuestion.difficulty}</span>
                  </div>
                )}
                {analysis && (
                  <div className="analysis">
                    <strong>{analysis.normalized_problem}</strong>
                    <span>Kỹ năng: {analysis.skills.join(", ") || "chưa xác định"}</span>
                    <span>Độ tin cậy đọc đề: {Math.round(analysis.confidence * 100)}%</span>
                  </div>
                )}
                {latestTutorTurn && (
                  <div className="sessionState">
                    <span>Tiến trình hiện tại</span>
                    <strong>{TUTOR_STATE_LABELS[latestTutorTurn.state]}</strong>
                  </div>
                )}
                <div className="chat">
                  {messages.map((message, index) => (
                    <div key={index} className={`bubble ${message.role}`}>
                      <b>{message.role === "tutor" ? "Gia sư" : "Học sinh"}</b>
                      {message.role === "tutor" && (
                        <div className="tutorMeta">
                          <span className="stateBadge">
                            {TUTOR_STATE_LABELS[message.turn.state]}
                          </span>
                          {message.turn.hint_level > 0 && (
                            <span>Mức gợi ý {message.turn.hint_level}</span>
                          )}
                          {message.turn.skill_tags.length > 0 && (
                            <span className="skillTags">
                              {message.turn.skill_tags.map((skill) => (
                                <span className="skillTag" key={skill}>{skill}</span>
                              ))}
                            </span>
                          )}
                        </div>
                      )}
                      <p>{message.content}</p>
                    </div>
                  ))}
                </div>
                {nextLearningAction && (
                  <section className="analysis" aria-label="Bài tiếp theo">
                    <h3>Bài tiếp theo</h3>
                    <p>{nextLearningAction.problem_text}</p>
                    <span>Kỹ năng: {nextLearningAction.skill_code}</span>
                    <span>Độ khó: {nextLearningAction.difficulty}</span>
                    <button type="button" disabled={busy || sessionStudentId === null} onClick={() => void startAuthoredTutor()}>
                      Bắt đầu bài này
                    </button>
                  </section>
                )}
                <form onSubmit={sendReply} className="reply">
                  <input disabled={busy} value={reply} onChange={(e) => setReply(e.target.value)} placeholder="Nhập suy nghĩ hoặc bước giải của em..." />
                  <button disabled={busy || !reply.trim()}>Gửi</button>
                </form>
                <div className="tutorActions">
                  {canRequestHint && (
                    <button
                      type="button"
                      className="secondary"
                      disabled={busy}
                      onClick={() => void submitTutorReply(HINT_REQUEST_MESSAGE, "hint_request")}
                    >
                      Xin gợi ý
                    </button>
                  )}
                  <button className="ghost" disabled={busy} onClick={() => {
                    setSessionId(null);
                    setSessionStudentId(null);
                    setPilotSessionStudentId(null);
                    setMessages([]);
                    setAnalysis(null);
                    setReply("");
                    setImageDataUrl(null);
                    setNextLearningAction(null);
                    setAuthoredQuestion(null);
                  }}>Bài mới</button>
                </div>
              </>
            )}
          </section>
        </div>
      )}
    </main>
  );
}

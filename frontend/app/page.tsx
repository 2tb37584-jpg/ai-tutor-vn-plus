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
    throw new Error(message);
  }
  return response.json();
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
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [reply, setReply] = useState("");
  const [analysis, setAnalysis] = useState<StartResponse["analysis"] | null>(null);
  const [nextLearningAction, setNextLearningAction] = useState<NextLearningAction | null>(null);
  const [authoredQuestion, setAuthoredQuestion] = useState<NextLearningAction | null>(null);
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const tutorRequestInFlight = useRef(false);

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
      if (!selectedStudent && data.length) setSelectedStudent(data[0].id);
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
      setSelectedStudent(student.id);
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
    if (!selectedStudent) {
      setStatus("Hãy tạo/chọn một học sinh trước.");
      return;
    }
    setBusy(true);
    setStatus("Đang phân tích bài...");
    try {
      const data = await api<StartResponse>("/tutor/start", {
        method: "POST",
        body: JSON.stringify({ student_id: selectedStudent, problem_text: problem, image_data_url: imageDataUrl }),
      }, token);
      setSessionId(data.session_id);
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
    if (!selectedStudent) {
      setStatus("Hãy tạo/chọn một học sinh trước.");
      return;
    }
    if (!nextLearningAction || busy) return;

    setBusy(true);
    setStatus("Đang bắt đầu bài được chọn...");
    try {
      const data = await api<StartAuthoredResponse>("/tutor/start-authored", {
        method: "POST",
        body: JSON.stringify({
          student_id: selectedStudent,
          question_id: nextLearningAction.question_id,
        }),
      }, token);
      setSessionId(data.session_id);
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
      setNextLearningAction(data.next_learning_action ?? null);
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
    setSelectedStudent(null);
    setSessionId(null);
    setMessages([]);
    setNextLearningAction(null);
    setAuthoredQuestion(null);
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
                  <button key={student.id} className={student.id === selectedStudent ? "student active" : "student"} onClick={() => setSelectedStudent(student.id)}>
                    <span>{student.display_name}</span><small>Lớp {student.grade ?? "?"}</small>
                  </button>
                ))}
              </div>
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
                    <button type="button" disabled={busy || !selectedStudent} onClick={() => void startAuthoredTutor()}>
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

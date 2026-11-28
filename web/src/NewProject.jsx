import { useEffect, useState } from "react";
import { api } from "./api";

const initialForm = { name: "", description: "", target_count: 100, width: 1024, height: 1024, style_notes: "", subject_mode: "recognizable", skill_id: "character-collection" };

export default function NewProject() {
  const [form, setForm] = useState(initialForm);
  const [meta, setMeta] = useState(null);
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState("");
  const [projectId, setProjectId] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { api("/api/meta").then(setMeta).catch((err) => setError(err.message)); }, []);
  useEffect(() => {
    if (!file) { setPreview(""); return; }
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);
  function field(key, value) { setForm((current) => ({ ...current, [key]: value })); }
  async function create(event) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    let id = projectId;
    try {
      if (!id) {
        const project = await api("/api/projects", { method: "POST", body: JSON.stringify(form) });
        id = project.id;
        setProjectId(id);
      }
      if (file) {
        const body = new FormData();
        body.append("file", file);
        await api(`/api/projects/${id}/reference`, { method: "POST", body });
      }
      window.location.hash = `#/studio/${id}`;
    } catch (err) {
      setError(id ? `项目已创建，参考图上传失败：${err.message}` : err.message);
    } finally { setBusy(false); }
  }
  return (
    <main className="new-project-page">
      <a className="btn-ghost" href="#/">← 返回</a>
      <form className="new-project-layout" onSubmit={create}>
        <aside className="new-project-reference">
          <div className="checker">{preview ? <img src={preview} alt="参考图预览" /> : <span>尚未选择参考图</span>}</div>
          <label className="btn-ghost" htmlFor="new-reference">{file ? "更换参考图" : "选择参考图"}</label>
          <input id="new-reference" type="file" accept="image/png,image/jpeg,image/webp" disabled={busy} onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
          <button className="btn-ghost" disabled={busy || !file} type="button" onClick={() => setFile(null)}>取消图片</button>
          <small className="muted">可选，也可以进入创作页后再上传。</small>
        </aside>
        <section className="new-project-fields">
          <h1>新建项目</h1>
          {error && <p className="error" role="alert">{error}</p>}
          <fieldset disabled={busy || !!projectId} className="new-project-grid">
            <label className="full-field">项目名称<input required value={form.name} onChange={(event) => field("name", event.target.value)} /></label>
            <label className="full-field">项目描述<textarea rows={2} placeholder="描述你想制作的系列" value={form.description} onChange={(event) => field("description", event.target.value)} /></label>
            <label>目标数量<input type="number" min="1" max="10000" required value={form.target_count} onChange={(event) => field("target_count", Number(event.target.value))} /></label>
            <label>画布尺寸<select value={form.width} onChange={(event) => { const size = Number(event.target.value); setForm({ ...form, width: size, height: size }); }}><option value={768}>768 × 768</option><option value={1024}>1024 × 1024</option></select></label>
            <label>主体改动模式<select value={form.subject_mode} onChange={(event) => field("subject_mode", event.target.value)}>{Object.entries(meta?.subject_modes ?? {}).map(([key, mode]) => <option key={key} value={key}>{mode.label}</option>)}</select><small className="muted">{meta?.subject_modes?.[form.subject_mode]?.note}</small></label>
            <label>内置技能<select value={form.skill_id} onChange={(event) => field("skill_id", event.target.value)}>{(meta?.skills ?? []).map((skill) => <option key={skill.id} value={skill.id}>{skill.name}</option>)}</select></label>
            <label className="full-field">生成偏好<textarea rows={2} value={form.style_notes} onChange={(event) => field("style_notes", event.target.value)} /></label>
          </fieldset>
          <footer className="actions new-project-actions"><a className="btn-ghost" href={projectId ? `#/studio/${projectId}` : "#/"}>{projectId ? "直接进入项目" : "取消"}</a><button className="btn" disabled={busy}>{busy ? "正在保存…" : projectId ? "重试上传" : "创建项目"}</button></footer>
        </section>
      </form>
    </main>
  );
}

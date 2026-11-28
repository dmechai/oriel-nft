import { useEffect, useState } from "react";
import { api } from "./api";
import { Mark } from "./mark.jsx";
import Studio from "./Studio.jsx";
import NewProject from "./NewProject.jsx";

function useHash() {
  const [hash, setHash] = useState(window.location.hash || "#/");
  useEffect(() => {
    const onChange = () => setHash(window.location.hash || "#/");
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return hash;
}

function Home() {
  const [projects, setProjects] = useState([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { api("/api/projects").then(setProjects).catch((err) => setError(err.message)); }, []);
  async function sample() {
    setBusy(true); setError("");
    try {
      const project = await api("/api/sample-project", { method: "POST", body: JSON.stringify({ count: 24 }) });
      window.location.hash = `#/studio/${project.id}`;
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  }
  const allFiles = projects.flatMap((project) => project.files);
  const hero = allFiles.find((file) => file.kind === "master") || allFiles.find((file) => file.kind === "reference");
  return (
    <main className="projects-page">
      <header className="projects-header">
        <a className="brand-lockup" href="#/"><Mark /> Oriel NFT</a>
        <nav className="projects-nav" aria-label="主导航"><a href="#/" aria-current="page">我的项目</a><a href="#/settings">接口设置</a></nav>
        <div className="actions"><button className="btn-ghost" onClick={sample} disabled={busy}>离线样例</button><a className="btn" href="#/new">＋ 新建项目</a></div>
      </header>
      <section className="lobby-main">
        <div className="projects-hero">{hero && <img src={hero.url} alt="" />}<div><h1>我的项目</h1><p>从参考图开始，制作你的 NFT 系列。</p></div></div>
        {error && <p className="error" role="alert">{error}</p>}
        {busy && <p>正在准备，样例会在本地直接合成，不调用模型。</p>}
        {!projects.length && !error && <p className="muted">还没有项目。可以新建项目，或打开不调用模型的离线样例。</p>}
        <div className="project-grid">
          {projects.map((project) => {
            const cover = project.files.find((file) => file.kind === "master") || project.files.find((file) => file.kind === "reference");
            const completed = [!!project.analysis, project.files.some((file) => file.kind === "concept"), project.files.some((file) => file.kind === "master"), !!project.plan?.categories?.length, project.files.some((file) => file.kind === "generated"), project.nft_count >= project.target_count].filter(Boolean).length;
            return <a key={project.id} className="project-card" href={`#/studio/${project.id}`}>
              <div className="thumb">{cover && <img src={cover.url} alt="" />}</div>
              <div className="project-card-copy"><strong>{project.name}</strong>{project.description && <span className="muted">{project.description}</span>}<span>{project.nft_count} / {project.target_count}</span><small className="muted">{completed ? `进行中 · ${completed} 阶段` : "尚未开始"}<span aria-hidden="true">→</span></small></div>
            </a>;
          })}
          <a className="project-card project-card-new" href="#/new"><span aria-hidden="true">＋</span><strong>新建项目</strong><small className="muted">从一张参考图开始</small></a>
        </div>
        <p className="muted">项目和图片保存在服务运行的主机。调用模型时，图片会发送至所选上游服务。</p>
      </section>
    </main>
  );
}

function Settings() {
  const blank = { name: "", base_url: "", api_key: "", vision_model: "", text_model: "", image_model: "", edit_model: "", image_api: "openai_images", is_default: true };
  const [rows, setRows] = useState([]);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState(blank);
  const [models, setModels] = useState([]);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  async function reload() { setRows(await api("/api/providers")); }
  useEffect(() => { reload().catch((err) => setError(err.message)); }, []);
  function edit(row) {
    setEditing(true); setForm({ ...row, api_key: "" });
    setMessage(`正在编辑 ${row.name}。${row.has_key ? "Base URL 不变时，密钥留空可保留已保存的密钥。" : "当前未保存密钥。"}`);
  }
  async function save(event) {
    event.preventDefault(); setError("");
    try {
      if (form.id) await api(`/api/providers/${form.id}`, { method: "PUT", body: JSON.stringify(form) });
      else await api("/api/providers", { method: "POST", body: JSON.stringify(form) });
      setForm(blank); setEditing(false); setMessage("已保存。密钥只加密留在本机数据目录，不会出现在导出的系列里。"); await reload();
    } catch (err) { setError(err.message); }
  }
  async function pull(id) {
    setError("");
    try { const data = await api(`/api/providers/${id}/models`, { method: "POST" }); setModels(data.models); setMessage(`已读取 ${data.models.length} 个模型`); }
    catch (err) { setError(err.message); }
  }
  async function test(id) {
    setError("");
    try { const data = await api(`/api/providers/${id}/test`, { method: "POST" }); setMessage(`对话测试返回：${data.reply}。这次调用会使用你的额度。`); }
    catch (err) { setError(err.message); }
  }
  return (
    <main className="settings-page">
      <aside className="settings-nav"><a className="brand-lockup" href="#/"><Mark /> Oriel NFT</a><nav aria-label="设置导航"><a href="#/">项目列表</a><a href="#/settings" aria-current="page">接口设置</a></nav></aside>
      <section className="settings-main">
        <div className="toolbar"><div><h1>Provider 设置</h1><p className="muted">配置 OpenAI 兼容中转站或本地服务。使用远程接口时，参考图会发给该服务。</p></div><button className="btn-ghost" onClick={() => { setForm(blank); setMessage(""); setError(""); setEditing(true); }}>＋ 添加 Provider</button></div>
        {error && <p className="error" role="alert">{error}</p>}{message && <p>{message}</p>}
        {!rows.length && !editing && <p className="empty">还没有配置接口。</p>}
        <div className="provider-list">{rows.map((row) => <article key={row.id} className="sheet provider-row">
          <div><strong>{row.name}</strong> {row.is_default && <small className="provider-default">默认</small>}<div className="muted">{row.base_url}</div></div>
          <div className="muted">{row.has_key ? "已保存密钥" : "未使用密钥"} · {row.image_api === "chat_image" ? "对话出图" : "Images 接口"}<br />模型：{row.image_model || "未配置"}</div>
          <div className="actions"><button className="btn-ghost" onClick={() => edit(row)}>编辑</button><button className="btn-ghost" onClick={() => pull(row.id)}>拉取模型</button><button className="btn-ghost" onClick={() => test(row.id)}>测试对话</button><button className="btn-danger" onClick={() => { if (window.confirm(`删除接口「${row.name}」？`)) api(`/api/providers/${row.id}`, { method: "DELETE" }).then(reload).catch((err) => setError(err.message)); }}>删除</button></div>
        </article>)}</div>
        {editing && <form className="sheet form-grid provider-form" onSubmit={save}>
          <h3>{form.id ? "编辑接口" : "添加接口"}</h3>
          <label>名称<input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} required /></label>
          <label>Base URL<input value={form.base_url} onChange={(event) => setForm({ ...form, base_url: event.target.value })} placeholder="https://example.com/v1" required /></label>
          <label>API Key<input type="password" value={form.api_key} onChange={(event) => setForm({ ...form, api_key: event.target.value })} placeholder={form.id ? "留空则不更换" : "只保存在本机"} /></label>
          <label>出图方式<select value={form.image_api} onChange={(event) => setForm({ ...form, image_api: event.target.value })}><option value="openai_images">OpenAI Images / images/edits</option><option value="chat_image">对话接口返回图片</option></select></label>
          {Object.entries({ vision_model: "视觉模型", text_model: "规划模型", image_model: "图像生成模型", edit_model: "参考图编辑模型（留空则沿用生成模型）" }).map(([key, label]) => <label key={key}>{label}<input list="model-list" value={form[key]} onChange={(event) => setForm({ ...form, [key]: event.target.value })} /></label>)}
          <datalist id="model-list">{models.map((model) => <option key={model} value={model} />)}</datalist>
          <label><input type="checkbox" checked={!!form.is_default} onChange={(event) => setForm({ ...form, is_default: event.target.checked })} /> 作为默认接口</label>
          <div className="actions"><button className="btn-ghost" type="button" onClick={() => setEditing(false)}>取消</button><button className="btn">保存</button></div>
        </form>}
      </section>
    </main>
  );
}

export default function App() {
  const hash = useHash();
  if (hash === "#/new") return <NewProject />;
  if (hash.startsWith("#/settings")) return <Settings />;
  if (hash.startsWith("#/studio/")) return <Studio id={hash.split("/")[2]} />;
  return <Home />;
}

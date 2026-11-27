import { useEffect, useState } from "react";
import { api } from "./api";
import { Mark } from "./mark.jsx";
import Studio from "./Studio.jsx";

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
  const [meta, setMeta] = useState(null);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({
    name: "",
    description: "",
    target_count: 100,
    width: 1024,
    height: 1024,
    style_notes: "",
    subject_mode: "recognizable",
    skill_id: "character-collection",
  });

  async function reload() {
    const [rows, info] = await Promise.all([api("/api/projects"), api("/api/meta")]);
    setProjects(rows);
    setMeta(info);
  }

  useEffect(() => {
    reload().catch((err) => setError(err.message));
  }, []);

  async function create(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const project = await api("/api/projects", { method: "POST", body: JSON.stringify(form) });
      window.location.hash = `#/studio/${project.id}`;
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function sample() {
    setBusy(true);
    setError("");
    try {
      const project = await api("/api/sample-project", { method: "POST", body: JSON.stringify({ count: 24 }) });
      window.location.hash = `#/studio/${project.id}`;
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const modes = meta ? Object.entries(meta.subject_modes) : [];

  return (
    <main className="lobby">
      <section className="lobby-brand">
        <p className="brand-lockup"><Mark /> Oriel NFT</p>
        <h1>一张图，做成一套。</h1>
        <p className="lede">上传参考图，先选定风格方向，再锁定主图。属性可以变，渲染语言不能变。</p>
        <p className="brand-note">项目和图片保存在此服务运行的主机。模型接口与密钥由部署者自行配置；调用模型会将图片发送至所选上游服务。</p>
      </section>
      <section className="lobby-main">
        <div className="toolbar">
          <div>
            <h2>项目</h2>
            <p className="muted">项目、图片和导出文件都留在你的机器上。</p>
          </div>
          <div className="actions">
            <a className="btn-ghost" href="#/settings">接口设置</a>
            <button className="btn-ghost" onClick={sample} disabled={busy}>打开离线样例</button>
            <button className="btn" onClick={() => setOpen(true)}>新建系列</button>
          </div>
        </div>
        {error && <p className="error">{error}</p>}
        {busy && <p>正在准备，样例会在本地直接合成，不调用模型。</p>}
        {projects.length === 0 ? (
          <div className="empty">还没有系列。可以新建一个，或先打开灯狐样例看组合、稀有度和导出。</div>
        ) : (
          <div className="project-grid">
            {projects.map((project) => {
              const cover = project.files.find((file) => file.kind === "master") || project.files.find((file) => file.kind === "reference");
              return (
                <button key={project.id} className="project-card" onClick={() => { window.location.hash = `#/studio/${project.id}`; }}>
                  <div className="thumb">{cover && <img src={cover.url} alt="" />}</div>
                  <div>
                    <strong>{project.name}</strong>
                    <span className="muted">{project.nft_count} 张 · 目标 {project.target_count}</span>
                  </div>
                </button>
              );
            })}
          </div>
        )}
        {open && (
          <form className="sheet form-grid" onSubmit={create} style={{ marginTop: 18 }}>
            <h3>新系列</h3>
            <label>名称<input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} required /></label>
            <label>描述<textarea value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} /></label>
            <label>目标数量<input type="number" min="1" max="10000" value={form.target_count} onChange={(event) => setForm({ ...form, target_count: Number(event.target.value) })} /></label>
            <label>边长
              <select value={form.width} onChange={(event) => setForm({ ...form, width: Number(event.target.value), height: Number(event.target.value) })}>
                <option value={768}>768</option>
                <option value={1024}>1024</option>
              </select>
            </label>
            <label>生成偏好<textarea value={form.style_notes} onChange={(event) => setForm({ ...form, style_notes: event.target.value })} placeholder="例如：保留角色，背景安静，不要写实光。" /></label>
            <div className="mode">
              {modes.map(([id, mode]) => (
                <label key={id} className={form.subject_mode === id ? "on" : ""}>
                  <input type="radio" name="mode" checked={form.subject_mode === id} onChange={() => setForm({ ...form, subject_mode: id })} /> {mode.label}
                  <small>{mode.note}</small>
                </label>
              ))}
            </div>
            <label>内置技能
              <select value={form.skill_id} onChange={(event) => setForm({ ...form, skill_id: event.target.value })}>
                {(meta?.skills || []).map((skill) => <option key={skill.id} value={skill.id}>{skill.name}</option>)}
              </select>
            </label>
            <div className="actions">
              <button className="btn" disabled={busy}>创建并进入</button>
              <button className="btn-ghost" type="button" onClick={() => setOpen(false)}>取消</button>
            </div>
          </form>
        )}
      </section>
    </main>
  );
}

function Settings() {
  const blank = { name: "", base_url: "", api_key: "", vision_model: "", text_model: "", image_model: "", edit_model: "", image_api: "openai_images", is_default: true };
  const [rows, setRows] = useState([]);
  const [form, setForm] = useState(blank);
  const [models, setModels] = useState([]);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  async function reload() {
    setRows(await api("/api/providers"));
  }
  useEffect(() => { reload().catch((err) => setError(err.message)); }, []);

  function edit(row) {
    setForm({ ...row, api_key: "" });
    setMessage(`正在编辑 ${row.name}。${row.has_key ? "Base URL 不变时，密钥留空可保留已保存的密钥。" : "当前未保存密钥。"}`);
  }

  async function save(event) {
    event.preventDefault();
    setError("");
    try {
      if (form.id) await api(`/api/providers/${form.id}`, { method: "PUT", body: JSON.stringify(form) });
      else await api("/api/providers", { method: "POST", body: JSON.stringify(form) });
      setForm(blank);
      setMessage("已保存。密钥只加密留在本机数据目录，不会出现在导出的系列里。");
      await reload();
    } catch (err) {
      setError(err.message);
    }
  }

  async function pull(id) {
    setError("");
    try {
      const data = await api(`/api/providers/${id}/models`, { method: "POST" });
      setModels(data.models);
      setMessage("已从上游拉取模型列表。参考图编辑能力需要单独验证。");
    } catch (err) {
      setError(err.message);
    }
  }

  async function test(id) {
    setError("");
    try {
      const data = await api(`/api/providers/${id}/test`, { method: "POST" });
      setMessage(`对话测试返回：${data.reply}。这次调用会使用你的额度。`);
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <main className="lobby">
      <section className="lobby-brand">
        <a className="brand-lockup" href="#/"><Mark /> Oriel NFT</a>
        <h1>你的接口，你的额度。</h1>
        <p className="lede">填写 OpenAI 兼容的 Base URL 和密钥。分析、规划和出图可以各选一个模型。</p>
        <p className="brand-note">使用远程接口时，参考图或主图会发给该服务。调用前项目会再提醒一次。</p>
      </section>
      <section className="lobby-main">
        <div className="toolbar">
          <h2>接口</h2>
          <a className="btn-ghost" href="#/">返回</a>
        </div>
        {error && <p className="error">{error}</p>}
        {message && <p>{message}</p>}
        <div className="project-grid">
          {rows.map((row) => (
            <article key={row.id} className="sheet">
              <strong>{row.name}</strong>
              <p className="muted">{row.base_url}</p>
              <p className="muted">{row.has_key ? "已保存密钥" : "未使用密钥"} · {row.image_api === "chat_image" ? "对话出图" : "Images 接口"}</p>
              <div className="actions">
                <button className="btn-ghost" onClick={() => edit(row)}>编辑</button>
                <button className="btn-ghost" onClick={() => pull(row.id)}>拉取模型</button>
                <button className="btn-ghost" onClick={() => test(row.id)}>测试对话</button>
                <button className="btn-danger" onClick={() => api(`/api/providers/${row.id}`, { method: "DELETE" }).then(reload)}>删除</button>
              </div>
            </article>
          ))}
        </div>
        <form className="sheet form-grid" onSubmit={save} style={{ marginTop: 16 }}>
          <h3>{form.id ? "编辑接口" : "添加接口"}</h3>
          <label>名称<input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} required /></label>
          <label>Base URL<input value={form.base_url} onChange={(event) => setForm({ ...form, base_url: event.target.value })} placeholder="https://example.com/v1" required /></label>
          <label>API Key<input type="password" value={form.api_key} onChange={(event) => setForm({ ...form, api_key: event.target.value })} placeholder={form.id ? "留空则不更换" : "只保存在本机"} /></label>
          <label>出图方式
            <select value={form.image_api} onChange={(event) => setForm({ ...form, image_api: event.target.value })}>
              <option value="openai_images">OpenAI Images / images/edits</option>
              <option value="chat_image">对话接口返回图片</option>
            </select>
          </label>
          {Object.entries({ vision_model: "视觉模型", text_model: "规划模型", image_model: "图像生成模型", edit_model: "参考图编辑模型（留空则沿用生成模型）" }).map(([key, label]) => (
            <label key={key}>{label}
              <input list="model-list" value={form[key]} onChange={(event) => setForm({ ...form, [key]: event.target.value })} />
            </label>
          ))}
          <datalist id="model-list">{models.map((model) => <option key={model} value={model} />)}</datalist>
          <label><input type="checkbox" checked={!!form.is_default} onChange={(event) => setForm({ ...form, is_default: event.target.checked })} /> 作为默认接口</label>
          <button className="btn">保存</button>
        </form>
      </section>
    </main>
  );
}

export default function App() {
  const hash = useHash();
  if (hash.startsWith("#/settings")) return <Settings />;
  if (hash.startsWith("#/studio/")) return <Studio id={decodeURIComponent(hash.split("/")[2] || "")} />;
  return <Home />;
}

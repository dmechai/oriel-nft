import { useEffect, useState } from "react";
import { api, waitJob } from "./api";
import { Mark } from "./mark.jsx";

const STAGES = [
  ["reference", "参考"],
  ["direction", "方向"],
  ["master", "主图"],
  ["traits", "属性"],
  ["assets", "素材"],
  ["collection", "系列"],
];

const EMPTY_ANALYSIS = {
  subject: "", structure: "", style: "", palette: [], lighting: "", composition: "", keep: [], vary: [], ambiguous: "", warnings: [], suggested_skill: "character-collection",
};

function lines(value) {
  return Array.isArray(value) ? value.join("\n") : value || "";
}
function splitLines(value) {
  return value.split("\n").map((item) => item.trim()).filter(Boolean);
}
function isRemote(provider) {
  if (!provider) return false;
  try {
    const host = new URL(provider.base_url).hostname;
    return !["localhost", "127.0.0.1", "::1"].includes(host);
  } catch {
    return true;
  }
}

export default function Studio({ id }) {
  const [project, setProject] = useState(null);
  const [meta, setMeta] = useState(null);
  const [providers, setProviders] = useState([]);
  const [stage, setStage] = useState("reference");
  const [error, setError] = useState("");
  const [job, setJob] = useState(null);
  const [analysis, setAnalysis] = useState(EMPTY_ANALYSIS);
  const [plan, setPlan] = useState({ categories: [], rules: [] });
  const [contract, setContract] = useState(null);
  const [selectedConcept, setSelectedConcept] = useState("");
  const [instruction, setInstruction] = useState("");
  const [selectedCategory, setSelectedCategory] = useState(0);
  const [nfts, setNfts] = useState([]);
  const [stats, setStats] = useState(null);
  const [selectedNft, setSelectedNft] = useState(null);
  const [nftPage, setNftPage] = useState(0);
  const [traitEdits, setTraitEdits] = useState({});
  const pageSize = 48;

  async function loadNftPage(index) {
    const page = await api(`/api/projects/${id}/nfts?limit=${pageSize}&offset=${index * pageSize}`);
    setNftPage(index);
    setNfts(page.items);
    setSelectedNft((current) => page.items.find((item) => item.id === current?.id) || null);
  }

  async function reload() {
    const [next, info, providerRows] = await Promise.all([
      api(`/api/projects/${id}`),
      api("/api/meta"),
      api("/api/providers"),
    ]);
    setProject(next);
    setMeta(info);
    setProviders(providerRows);
    setAnalysis(next.analysis || EMPTY_ANALYSIS);
    setPlan(next.plan || { categories: [], rules: [] });
    setContract(next.style_contract);
    const concepts = next.files.filter((file) => file.kind === "concept");
    setSelectedConcept((current) => concepts.some((file) => file.id === current) ? current : concepts[0]?.id || "");
    if (next.nft_count) {
      await loadNftPage(Math.min(nftPage, Math.ceil(next.nft_count / pageSize) - 1));
      setStats(await api(`/api/projects/${id}/stats`));
    } else {
      setNfts([]);
      setStats(null);
    }
  }

  useEffect(() => {
    reload().catch((err) => setError(err.message));
  }, [id]);

  if (!project || !meta) return <main className="studio"><p style={{ padding: 24 }}>{error || "正在打开工作室…"}</p></main>;

  const provider = providers.find((item) => item.id === project.provider_id) || providers.find((item) => item.is_default) || providers[0];
  const reference = project.files.find((file) => file.kind === "reference");
  const concepts = project.files.filter((file) => file.kind === "concept");
  const master = project.files.find((file) => file.kind === "master");
  const cutout = project.files.find((file) => file.kind === "cutout");
  const category = plan.categories[selectedCategory];

  async function saveProject(patch) {
    setError("");
    try {
      const next = await api(`/api/projects/${id}`, { method: "PATCH", body: JSON.stringify(patch) });
      setProject(next);
    } catch (err) {
      setError(err.message);
    }
  }

  async function confirmRemote() {
    if (!provider || !isRemote(provider)) return true;
    const key = `oriel-remote-${provider.id}-${provider.base_url}`;
    if (sessionStorage.getItem(key)) return true;
    const ok = window.confirm(`接下来的图片会发送到 ${provider.base_url}。费用由该接口计收，Oriel 不经手密钥。继续？`);
    if (ok) sessionStorage.setItem(key, "1");
    return ok;
  }

  async function runJob(path, options, usesProvider = true) {
    setError("");
    if (job?.status === "running" || (usesProvider && !(await confirmRemote()))) return;
    setJob({ status: "running", message: "正在提交", progress: 4 });
    try {
      const started = await api(path, options);
      const done = await waitJob(started.job_id, setJob);
      if (done.status === "error") throw new Error(done.message || "任务失败");
      await reload();
      if (done.kind === "refine") setSelectedConcept(done.result.id);
    } catch (err) {
      setJob(null);
      await reload().catch(() => {});
      throw err;
    }
  }

  async function upload(file) {
    const body = new FormData();
    body.append("file", file);
    await api(`/api/projects/${id}/reference`, { method: "POST", body });
    await reload();
  }

  async function saveAnalysis() {
    const next = await api(`/api/projects/${id}/analysis`, {
      method: "PUT",
      body: JSON.stringify({ ...analysis, source: "edited" }),
    });
    setProject(next);
    setAnalysis(next.analysis);
  }

  async function savePlan() {
    const next = await api(`/api/projects/${id}/plan`, { method: "PUT", body: JSON.stringify(plan) });
    setProject(next);
    setPlan(next.plan);
  }

  async function saveContract() {
    const next = await api(`/api/projects/${id}/contract`, { method: "PUT", body: JSON.stringify(contract) });
    setProject(next);
    setContract(next.style_contract);
    setPlan(next.plan);
  }

  function updateCategory(patch) {
    const categories = plan.categories.map((item, index) => index === selectedCategory ? { ...item, ...patch } : item);
    setPlan({ ...plan, categories });
  }

  function updateValue(valueIndex, patch) {
    const values = category.values.map((item, index) => index === valueIndex ? { ...item, ...patch } : item);
    updateCategory({ values });
  }

  function removeValues(ids, categories) {
    const rules = plan.rules.filter((rule) => !ids.includes(rule.left) && !ids.includes(rule.right));
    setPlan({ categories, rules });
  }

  function updateRule(ruleIndex, patch) {
    setPlan({ ...plan, rules: plan.rules.map((rule, index) => index === ruleIndex ? { ...rule, ...patch } : rule) });
  }

  async function exportZip() {
    const response = await api(`/api/projects/${id}/export`, { method: "POST" });
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${project.name}-collection.zip`;
    link.click();
    URL.revokeObjectURL(url);
  }

  const weakReference = concepts.some((file) => file.meta?.reference_sent === false);

  return (
    <main className="studio">
      <header className="topbar">
        <a href="#/"><Mark /></a>
        <div>
          <h1>{project.name}</h1>
          <div className="muted">{provider ? provider.name : "未配置接口"} · 目标 {project.target_count} 张</div>
        </div>
        <div className="spacer" />
        <a className="btn-ghost" href="#/settings">接口</a>
        <button className="btn" onClick={() => exportZip().catch((err) => setError(err.message))} disabled={!project.nft_count}>导出</button>
      </header>
      <div className="studio-body">
        <nav className="rail">
          {STAGES.map(([key, label], index) => (
            <button key={key} className={stage === key ? "on" : ""} onClick={() => setStage(key)}>
              <em>0{index + 1}</em>{label}
            </button>
          ))}
        </nav>
        <section className="stage">
          <h2>{STAGES.find((item) => item[0] === stage)?.[1]}</h2>
          {error && <p className="error">{error}</p>}
          {job && job.status !== "done" && (
            <div className="job">
              <div>{job.message}</div>
              <div className="bar"><span style={{ width: `${job.progress || 8}%` }} /></div>
            </div>
          )}

          {stage === "reference" && (
            <>
              <p className="muted">什么图都可以先分析。多人或含义不清时，只需要回答工作室提出的那一个问题。</p>
              <div className="hero checker">{reference ? <img src={reference.url} alt="参考图" /> : <div style={{ padding: 48 }}>还没有参考图</div>}</div>
              <div className="row" style={{ marginTop: 12 }}>
                <button className="btn-ghost" disabled={!!master || job?.status === "running"} type="button" onClick={() => document.getElementById("reference-upload").click()}>上传参考图</button>
                <input id="reference-upload" hidden type="file" accept="image/png,image/jpeg,image/webp" onChange={(event) => event.target.files?.[0] && upload(event.target.files[0]).catch((err) => setError(err.message))} />
                <button className="btn" disabled={!reference || !!master || job?.status === "running"} onClick={() => runJob(`/api/projects/${id}/analyze`, { method: "POST" }).catch((err) => setError(err.message))}>分析</button>
              </div>
              {analysis.ambiguous && <div className="warn">{analysis.ambiguous}</div>}
              {analysis.source === "local" && <div className="callout">这是本地预分析，没有调用模型。可以先填写主体，再生成方向图。</div>}
            </>
          )}

          {stage === "direction" && (
            <>
              <p className="muted">三张是三种完整方向，不是三个滤镜。选定后只用语言精修，确认前不会进入批量。</p>
              {weakReference && <div className="warn">当前图像接口没有接收参考图，只按文字生成。一致性会下降，建议换用支持编辑或对话出图的模型。</div>}
              <div className="concept-grid">
                {concepts.map((file) => (
                  <button key={file.id} className={selectedConcept === file.id ? "tile on" : "tile"} onClick={() => setSelectedConcept(file.id)}>
                    <div className="checker"><img src={file.url} alt={file.label} /></div>
                    <span>{file.label}</span>
                    <small className="muted">{file.meta?.reference_sent === false ? "未发送参考图" : "已参考原图"}</small>
                  </button>
                ))}
                {concepts.length === 0 && <div className="callout">还没有方向图。需要先有主体描述，并配置图像模型。</div>}
              </div>
              <div className="row" style={{ marginTop: 12 }}>
                <button className="btn" disabled={!provider || !!master || job?.status === "running"} onClick={() => runJob(`/api/projects/${id}/concepts`, { method: "POST" }).catch((err) => setError(err.message))}>生成三种方向</button>
              </div>
            </>
          )}

          {stage === "master" && (
            <>
              <p className="muted">锁定之后，整套 NFT 只对齐这张主图。仅取灵感档位不再回头对齐原图。</p>
              <div className="hero checker">{(master || concepts.find((file) => file.id === selectedConcept)) && <img src={(master || concepts.find((file) => file.id === selectedConcept)).url} alt="主图" />}</div>
              <div className="row" style={{ marginTop: 12 }}>
                <button className="btn" disabled={!!master || !selectedConcept || job?.status === "running"} onClick={() => runJob(`/api/projects/${id}/lock`, { method: "POST", body: JSON.stringify({ file_id: selectedConcept }) }).catch((err) => setError(err.message))}>锁定这张候选</button>
                <button className="btn-ghost" disabled={!master || job?.status === "running"} onClick={() => runJob(`/api/projects/${id}/cutout`, { method: "POST" }, false).catch((err) => setError(err.message))}>本地分离主体</button>
                <button className="btn-ghost" disabled={!master || !provider || job?.status === "running"} onClick={() => runJob(`/api/projects/${id}/cutout?use_model=true`, { method: "POST" }).catch((err) => setError(err.message))}>模型分离</button>
              </div>
              {cutout && <div className="hero checker" style={{ marginTop: 12 }}><img src={cutout.url} alt="主体分离" /></div>}
            </>
          )}

          {stage === "traits" && (
            <>
              <p className="muted">能拆开的做成图层。衣服、姿势和复杂特效用少量整体基底，避免贴纸感。</p>
              <button className="btn" disabled={!provider || !master || job?.status === "running"} onClick={() => runJob(`/api/projects/${id}/plan`, { method: "POST" }).catch((err) => setError(err.message))}>让模型规划属性</button>
              <div className="row" style={{ margin: "12px 0" }}>
                {plan.categories.map((item, index) => (
                  <button key={item.id} className={index === selectedCategory ? "btn" : "btn-ghost"} onClick={() => setSelectedCategory(index)}>{item.name}</button>
                ))}
                <button className="btn-ghost" onClick={() => {
                  const item = { id: `cat-${Date.now()}`, name: "新属性", z: plan.categories.length * 10, method: "overlay", region: { x: 0.3, y: 0.12, w: 0.4, h: 0.24 }, values: [{ id: `value-${Date.now()}`, name: "基础", weight: 40, prompt: "", asset_id: null, approved: false }] };
                  setPlan({ ...plan, categories: [...plan.categories, item] });
                  setSelectedCategory(plan.categories.length);
                }}>添加属性</button>
                <button className="btn" disabled={!master || job?.status === "running"} onClick={() => savePlan().catch((err) => setError(err.message))}>保存属性</button>
              </div>
            </>
          )}

          {stage === "assets" && (
            <>
              <p className="muted">素材必须通过你的确认才进入合成。不合风格的，重做，不硬拼。</p>
              <button className="btn" disabled={!provider || job?.status === "running"} onClick={() => runJob(`/api/projects/${id}/assets`, { method: "POST" }).catch((err) => setError(err.message))}>生成未通过的素材</button>
              <div className="asset-grid" style={{ marginTop: 14 }}>
                {plan.categories.flatMap((item) => item.values.map((value) => {
                  const file = project.files.find((asset) => asset.id === value.asset_id);
                  return (
                    <article key={value.id} className="tile">
                      <div className="checker">{file && <img src={file.url} alt="" />}</div>
                      <span>{item.name} / {value.name}</span>
                      <small className="muted">{value.approved ? "已通过" : "待确认"} {file?.meta?.warning || ""}</small>
                      <div className="row" style={{ padding: 8 }}>
                        <button className="btn-ghost" disabled={!value.asset_id || (!value.approved && !!file?.meta?.warning)} onClick={() => api(`/api/projects/${id}/values/${value.id}/approval`, { method: "POST", body: JSON.stringify({ approved: !value.approved }) }).then(reload).catch((err) => setError(err.message))}>{value.approved ? "撤回" : "通过"}</button>
                        <button className="btn-ghost" disabled={!provider} onClick={() => runJob(`/api/projects/${id}/assets?value_id=${value.id}`, { method: "POST" }).catch((err) => setError(err.message))}>重做</button>
                      </div>
                    </article>
                  );
                }))}
              </div>
            </>
          )}

          {stage === "collection" && (
            <>
              <p className="muted">正式出图由程序按已通过素材合成。数量不够时会停下，不用重复图凑数。近似图只标记，不自动删除。</p>
              <div className="row">
                <button className="btn-ghost" disabled={job?.status === "running"} onClick={() => runJob(`/api/projects/${id}/trial`, { method: "POST" }, false).catch((err) => setError(err.message))}>试生成样张</button>
                <button className="btn" disabled={!project.trial?.approved || job?.status === "running"} onClick={() => runJob(`/api/projects/${id}/collection`, { method: "POST" }, false).catch((err) => setError(err.message))}>生成 {project.target_count} 张</button>
                <button className="btn-ghost" onClick={() => exportZip().catch((err) => setError(err.message))} disabled={!nfts.length}>导出 ZIP</button>
              </div>
              {project.trial?.ready && (
                <section className="callout">
                  <h3>样张确认</h3>
                  <div className="nft-grid">
                    {project.trial.images.map((image, index) => (
                      <a className="tile" key={image.url} href={image.url} target="_blank" rel="noreferrer">
                        <img src={image.url} alt={`样张 ${index + 1}`} />
                        {image.warning && <small>{image.warning}</small>}
                      </a>
                    ))}
                  </div>
                  <p>确认主体比例、线条、光照和图层边缘一致后，即可生成整套。</p>
                  <button className="btn" disabled={project.trial.approved || job?.status === "running"} onClick={() => api(`/api/projects/${id}/trial/approve`, { method: "POST" }).then(reload).catch((err) => setError(err.message))}>{project.trial.approved ? "样张已确认" : "确认样张"}</button>
                </section>
              )}
              {stats && <p className="muted">已生成 {stats.total} 张，{stats.flagged} 张被标记为视觉接近。</p>}
              <div className="nft-grid" style={{ marginTop: 14 }}>
                {nfts.map((nft) => (
                  <button key={nft.id} className={selectedNft?.id === nft.id ? "tile on" : "tile"} onClick={() => { setSelectedNft(nft); setTraitEdits({}); }}>
                    <div className="checker"><img src={nft.url} alt={`#${nft.token_id}`} /></div>
                    <span>#{nft.token_id} {nft.locked ? "锁定" : ""} {nft.flagged ? "近似" : ""}</span>
                  </button>
                ))}
              </div>
              {project.nft_count > pageSize && <div className="row" style={{ marginTop: 12 }}>
                <button className="btn-ghost" disabled={!nftPage} onClick={() => loadNftPage(nftPage - 1).catch((err) => setError(err.message))}>上一页</button>
                <span>{nftPage + 1} / {Math.ceil(project.nft_count / pageSize)}</span>
                <button className="btn-ghost" disabled={(nftPage + 1) * pageSize >= project.nft_count} onClick={() => loadNftPage(nftPage + 1).catch((err) => setError(err.message))}>下一页</button>
              </div>}
            </>
          )}
        </section>
        <aside className="inspector">
          {stage === "reference" && (
            <div className="form-grid">
              <h3>这一步怎么处理主体</h3>
              <div className="mode">
                {Object.entries(meta.subject_modes).map(([key, mode]) => (
                  <label key={key} className={project.subject_mode === key ? "on" : ""}>
                    <input type="radio" name="subject" disabled={!!master} checked={project.subject_mode === key} onChange={() => saveProject({ subject_mode: key })} /> {mode.label}
                    <small>{mode.note}</small>
                  </label>
                ))}
              </div>
              <label>技能
                <select disabled={!!master} value={project.skill_id || ""} onChange={(event) => saveProject({ skill_id: event.target.value })}>
                  {meta.skills.map((skill) => <option key={skill.id} value={skill.id}>{skill.name}</option>)}
                </select>
              </label>
              <p className="muted">{meta.skills.find((skill) => skill.id === project.skill_id)?.summary}</p>
              <label>偏好<textarea disabled={!!master} value={project.style_notes} onChange={(event) => setProject({ ...project, style_notes: event.target.value })} onBlur={() => saveProject({ style_notes: project.style_notes })} /></label>
              <h3>分析结果</h3>
              <label>主体<input value={analysis.subject || ""} onChange={(event) => setAnalysis({ ...analysis, subject: event.target.value })} /></label>
              <label>保持不变<textarea value={lines(analysis.keep)} onChange={(event) => setAnalysis({ ...analysis, keep: splitLines(event.target.value) })} /></label>
              <label>适合变化<textarea value={lines(analysis.vary)} onChange={(event) => setAnalysis({ ...analysis, vary: splitLines(event.target.value) })} /></label>
              <button className="btn" disabled={!!master} onClick={() => saveAnalysis().catch((err) => setError(err.message))}>保存分析</button>
            </div>
          )}
          {stage === "direction" && (
            <div className="form-grid">
              <h3>语言精修</h3>
              <p className="muted">只改选定的那一张，不把三种方向混在一起。</p>
              <textarea value={instruction} onChange={(event) => setInstruction(event.target.value)} placeholder="保留轮廓，线条更粗，背景再安静一点。" />
              <button className="btn" disabled={!selectedConcept || !provider || !!master || job?.status === "running"} onClick={() => runJob(`/api/projects/${id}/refine`, { method: "POST", body: JSON.stringify({ file_id: selectedConcept, instruction }) }).catch((err) => setError(err.message))}>按这句话精修</button>
            </div>
          )}
          {stage === "master" && contract && (
            <div className="form-grid">
              <h3>风格合同</h3>
              <p className="muted">修改合同后，请重新审核素材并确认样张。</p>
              <label>渲染语言<textarea value={contract.summary || ""} onChange={(event) => setContract({ ...contract, summary: event.target.value })} /></label>
              <label>配色<textarea value={lines(contract.palette)} onChange={(event) => setContract({ ...contract, palette: splitLines(event.target.value) })} /></label>
              <label>线条<input value={contract.line || ""} onChange={(event) => setContract({ ...contract, line: event.target.value })} /></label>
              <label>光照<input value={contract.lighting || ""} onChange={(event) => setContract({ ...contract, lighting: event.target.value })} /></label>
              <label>材质<input value={contract.texture || ""} onChange={(event) => setContract({ ...contract, texture: event.target.value })} /></label>
              <label>构图<input value={contract.crop || ""} onChange={(event) => setContract({ ...contract, crop: event.target.value })} /></label>
              <label>身份锚点<textarea value={lines(contract.identity)} onChange={(event) => setContract({ ...contract, identity: splitLines(event.target.value) })} /></label>
              <label>排除项<textarea value={lines(contract.forbid)} onChange={(event) => setContract({ ...contract, forbid: splitLines(event.target.value) })} /></label>
              <button className="btn" onClick={() => saveContract().catch((err) => setError(err.message))}>保存合同</button>
              {!cutout && <div className="warn">还没有主体分离图。纯色背景可以本地分离；复杂背景再用模型。</div>}
            </div>
          )}
          {stage === "traits" && category && (
            <div className="form-grid">
              <h3>{category.name}</h3>
              <label>名称<input value={category.name} onChange={(event) => updateCategory({ name: event.target.value })} /></label>
              <label>方式
                <select value={category.method} onChange={(event) => updateCategory({ method: event.target.value })}>
                  <option value="background">背景层</option>
                  <option value="patch">局部补丁</option>
                  <option value="overlay">叠加配件</option>
                  <option value="base">整体基底</option>
                </select>
              </label>
              {category.method !== "background" && category.method !== "base" && category.region && (
                <>
                  {Object.entries({ x: "水平位置", y: "垂直位置", w: "宽度", h: "高度" }).map(([key, label]) => {
                    const { x, y, w, h } = category.region;
                    const max = { x: 1 - w, y: 1 - h, w: 1 - x, h: 1 - y }[key];
                    return <label key={key}>{label} {category.region[key]}<input type="range" min={key === "w" || key === "h" ? 0.01 : 0} max={max} step="0.01" value={category.region[key]} onChange={(event) => updateCategory({ region: { ...category.region, [key]: Number(event.target.value) } })} /></label>;
                  })}
                </>
              )}
              {category.values.map((value, index) => (
                <div key={value.id} className="trait">
                  <label>素材名<input value={value.name} onChange={(event) => updateValue(index, { name: event.target.value })} /></label>
                  <label>权重<input type="number" min="1" max="100" value={value.weight} onChange={(event) => updateValue(index, { weight: Number(event.target.value) })} /></label>
                  <label>描述<textarea value={value.prompt} onChange={(event) => updateValue(index, { prompt: event.target.value })} /></label>
                  <button className="btn-ghost" disabled={category.values.length === 1} onClick={() => removeValues([value.id], plan.categories.map((item) => item.id === category.id ? { ...item, values: item.values.filter((entry) => entry.id !== value.id) } : item))}>移除版本</button>
                </div>
              ))}
              <button className="btn-ghost" onClick={() => updateCategory({ values: [...category.values, { id: `value-${Date.now()}`, name: "新版本", weight: 10, prompt: "", asset_id: null, approved: false }] })}>添加版本</button>
              <button className="btn-ghost" onClick={() => {
                removeValues(category.values.map((value) => value.id), plan.categories.filter((item) => item.id !== category.id));
                setSelectedCategory(0);
              }}>移除属性</button>
              <h3>规则</h3>
              {plan.rules.map((rule, index) => (
                <div key={index} className="trait">
                  <select aria-label="规则类型" value={rule.type} onChange={(event) => updateRule(index, { type: event.target.value })}>
                    <option value="mutex">互斥</option>
                    <option value="requires">依赖</option>
                  </select>
                  {["left", "right"].map((side) => (
                    <select key={side} aria-label={side === "left" ? "第一个版本" : "第二个版本"} value={rule[side]} onChange={(event) => updateRule(index, { [side]: event.target.value })}>
                      <option value="" disabled>选择版本</option>
                      {plan.categories.map((item) => <optgroup key={item.id} label={item.name}>{item.values.map((value) => <option key={value.id} value={value.id}>{value.name}</option>)}</optgroup>)}
                    </select>
                  ))}
                  <button className="btn-ghost" onClick={() => setPlan({ ...plan, rules: plan.rules.filter((_, ruleIndex) => index !== ruleIndex) })}>移除规则</button>
                </div>
              ))}
              <button className="btn-ghost" onClick={() => setPlan({ ...plan, rules: [...plan.rules, { type: "mutex", left: "", right: "" }] })}>添加规则</button>
            </div>
          )}
          {stage === "assets" && (
            <div>
              <h3>一致性</h3>
              <p className="muted">通过前看三件事：是不是同一支线条，光有没有换方向，边缘像不像后贴上去的。</p>
              {(contract?.forbid || []).map((item) => <div key={item} className="callout">{item}</div>)}
            </div>
          )}
          {stage === "collection" && (
            <div>
              <h3>{selectedNft ? `#${selectedNft.token_id}` : "分布"}</h3>
              {selectedNft && (
                <div className="form-grid">
                  {selectedNft.attributes.map((attr) => <div key={attr.value_id}>{attr.trait_type}：{attr.value}</div>)}
                  {project.trial?.approved && !selectedNft.locked && plan.categories.map((item) => (
                    <label key={item.id}>{item.name}
                      <select value={traitEdits[item.id] ?? selectedNft.attributes.find((attr) => attr.category_id === item.id)?.value_id ?? ""} onChange={(event) => setTraitEdits({ ...traitEdits, [item.id]: event.target.value })}>
                        <option value="" disabled>选择版本</option>
                        {item.values.filter((value) => value.approved).map((value) => <option key={value.id} value={value.id}>{value.name}</option>)}
                      </select>
                    </label>
                  ))}
                  {Object.keys(traitEdits).length > 0 && !selectedNft.locked && <button className="btn" onClick={() => {
                    const values = plan.categories.map((item) => traitEdits[item.id] ?? selectedNft.attributes.find((attr) => attr.category_id === item.id)?.value_id);
                    api(`/api/projects/${id}/nfts/${selectedNft.id}`, { method: "PATCH", body: JSON.stringify({ values }) }).then(() => { setTraitEdits({}); return reload(); }).catch((err) => setError(err.message));
                  }}>保存这张的属性</button>}
                  {selectedNft.flagged && <div className="warn">{selectedNft.flag_reason}</div>}
                  <div className="row">
                    <button className="btn-ghost" onClick={() => api(`/api/projects/${id}/nfts/${selectedNft.id}`, { method: "PATCH", body: JSON.stringify({ locked: !selectedNft.locked }) }).then(reload).catch((err) => setError(err.message))}>{selectedNft.locked ? "解锁" : "锁定"}</button>
                    <button className="btn" disabled={selectedNft.locked || !project.trial?.approved} onClick={() => api(`/api/projects/${id}/nfts/${selectedNft.id}/reroll`, { method: "POST" }).then(reload).catch((err) => setError(err.message))}>重做这一张</button>
                  </div>
                </div>
              )}
              <div className="stats" style={{ marginTop: 16 }}>
                {(stats?.traits || []).map((row) => (
                  <div key={`${row.trait_type}-${row.value}`}>
                    <div className="stat"><span>{row.trait_type} / {row.value}</span><span>{row.percent}%</span></div>
                    <b style={{ width: `${Math.max(4, row.percent)}%` }} />
                  </div>
                ))}
              </div>
            </div>
          )}
        </aside>
      </div>
    </main>
  );
}

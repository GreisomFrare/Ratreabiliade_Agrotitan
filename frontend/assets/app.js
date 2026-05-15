/* ── layout: posiciona #mainArea abaixo de navbar + toolbar ─────────────── */
function _ajustarLayout() {
  const navbar  = document.getElementById('navbar');
  const toolbar = document.getElementById('toolbar');
  const main    = document.getElementById('mainArea');
  const top = navbar.offsetHeight + toolbar.offsetHeight;
  main.style.top = top + 'px';
}
window.addEventListener('resize', _ajustarLayout);
document.addEventListener('DOMContentLoaded', _ajustarLayout);

/* ── tema ───────────────────────────────────────────────────────────────── */
document.getElementById('btnTema').addEventListener('click', () => {
  const atual = document.documentElement.getAttribute('data-bs-theme');
  const novo  = atual === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-bs-theme', novo);
  localStorage.setItem('viasoft-theme', novo);
  if (network) _applyNetworkTheme();
});

/* ── formulário: adapta campos por tipo ─────────────────────────────────── */
const selTela   = document.getElementById('selTela');
const grpEstab  = document.getElementById('grpEstab');
const grpSerie  = document.getElementById('grpSerie');
const grpEmpresa= document.getElementById('grpEmpresa');
const lblDoc    = document.getElementById('lblDoc');

selTela.addEventListener('change', _adaptarCampos);
function _adaptarCampos() {
  const t = selTela.value;
  const usaEmpresa = t === 'DUPREC' || t === 'DUPPAG' || t === 'CONTAMOV';
  const usaEstab   = t === 'NFCAB'  || t === 'PEDCAB'  || t === 'CONTAMOV';
  grpEmpresa.style.display = usaEmpresa ? '' : 'none';
  grpEstab.style.display   = usaEstab   ? '' : 'none';
  grpSerie.style.display   = t === 'PEDCAB' ? '' : 'none';
  document.getElementById('lblEmpresa').textContent = t === 'CONTAMOV' ? 'Nº CM' : 'Empresa';
  lblDoc.textContent = {
    DUPREC:   'Número da Duplicata',
    DUPPAG:   'Número da Dup. a Pagar',
    NFCAB:    'Seq. Nota (SEQNOTA)',
    PEDCAB:   'Número do Pedido',
    CONTAMOV: 'Seq. CM (SEQCM)',
  }[t] || 'Número';
}

/* ── recibo: renderiza o campo REFERENTE (texto pipe-delimitado) ─────────── */
function _renderReferente(text) {
  if (!text) return '';
  const lines = text.split('\n');
  let html = '<div style="overflow-x:auto;margin-top:4px;">';
  let headerDone = false;

  for (const raw of lines) {
    const line = raw.trimEnd();
    if (!line.trim()) continue;
    if (/^-{10,}/.test(line.trim())) continue; // separador ---

    if (line.includes('|')) {
      const cells = line.split('|');
      // remove última célula vazia quando a linha termina em |
      const data = line.endsWith('|') ? cells.slice(0, -1) : cells;
      if (!headerDone) {
        html += '<table class="detalhe-table" style="font-size:0.68rem;white-space:nowrap;width:auto;">';
        html += '<thead><tr>' +
          data.map(c => `<th style="padding:2px 6px;color:var(--bs-secondary-color);text-align:right;">${c.trim()}</th>`).join('') +
          '</tr></thead><tbody>';
        headerDone = true;
      } else {
        html += '<tr>' +
          data.map(c => `<td style="padding:2px 6px;text-align:right;">${c.trim()}</td>`).join('') +
          '</tr>';
      }
    } else {
      if (headerDone) { html += '</tbody></table>'; headerDone = false; }
      html += `<p class="small text-muted mb-1 mt-1" style="font-size:0.72rem;">${line.trim()}</p>`;
    }
  }
  if (headerDone) html += '</tbody></table>';
  html += '</div>';
  return html;
}

/* ── vis-network ─────────────────────────────────────────────────────────── */
let network = null;
let nodesDS  = null;
let edgesDS  = null;

const NODE_COLORS = {
  PESSOA:     { bg:'#1a2a1a', border:'#6abf69', font:'#c8f0c8' },
  PEDCAB:     { bg:'#0d3466', border:'#4da3ff', font:'#cce4ff' },
  NFCAB:      { bg:'#0d3d22', border:'#2ecc71', font:'#c3f7d8' },
  PDUPREC:    { bg:'#4a2200', border:'#fd7e14', font:'#ffd4a8' },
  PDUPPAGA:   { bg:'#3d1a00', border:'#e8944a', font:'#ffc89a' },
  PRDUPREC:   { bg:'#2d1a55', border:'#a07be0', font:'#ddd0f7' },
  PPDUPPAG:   { bg:'#2a1540', border:'#b07de0', font:'#ddd0f7' },
  PLANCA:     { bg:'#063340', border:'#0dcaf0', font:'#b0eef9' },
  CONTAMOVLAN:  { bg:'#0a3028', border:'#20c997', font:'#b0f0e0' },
  CONTAMOVLANAC:{ bg:'#062030', border:'#00bcd4', font:'#aeefff' },
  PCHEQREC:   { bg:'#3d3000', border:'#ffc107', font:'#fff0b0' },
  PCHEQEMI:   { bg:'#3a2500', border:'#e8a800', font:'#ffe599' },
  PRDURECAR:  { bg:'#3d0a10', border:'#ff6680', font:'#ffb0bc' },
  ADIANTAMENTO:  { bg:'#2a1f00', border:'#d4a017', font:'#ffe898' },
  PRVDACAR:      { bg:'#2a0f1a', border:'#e83e8c', font:'#f9a8c9' },
  ACERCARTDIG:   { bg:'#002a25', border:'#32bcad', font:'#a0f0e8' },
};

function _nodeVisProps(type) {
  const dark = document.documentElement.getAttribute('data-bs-theme') === 'dark';
  const c = NODE_COLORS[type] || { bg:'#333', border:'#888', font:'#ddd' };
  return {
    color: {
      background:  dark ? c.bg     : '#ffffff',
      border:      c.border,
      highlight:   { background: dark ? c.bg : '#f0f7ff', border:'#ffffff' },
      hover:       { background: dark ? c.bg : '#f8f9fa', border: c.border },
    },
    font: { color: dark ? c.font : '#1a1a2e', size:13, face:'Segoe UI,sans-serif', multi:true },
  };
}

function _buildOptions() {
  const dark = document.documentElement.getAttribute('data-bs-theme') === 'dark';
  return {
    layout: {
      hierarchical: {
        enabled: true,
        direction: 'LR',
        sortMethod: 'directed',
        levelSeparation: 270,
        nodeSpacing: 120,
        treeSpacing: 150,
      },
    },
    physics: { enabled: false },
    edges: {
      arrows: { to: { enabled:true, scaleFactor:0.6 } },
      color:  { color: dark ? '#4a4a6a' : '#bbbbcc', highlight:'#4da3ff', hover:'#7ab0ff' },
      font:   { color: dark ? '#888' : '#666', size:10, align:'middle', strokeWidth:0 },
      smooth: { type:'cubicBezier', forceDirection:'horizontal', roundness:0.4 },
      width: 1.5,
    },
    nodes: {
      shape: 'box',
      borderWidth: 2,
      borderWidthSelected: 3,
      margin: { top:14, bottom:14, left:18, right:18 },
      shadow: { enabled: dark, size:6, color:'rgba(0,0,0,0.4)' },
    },
    interaction: { hover:true, tooltipDelay:200, zoomView:true, dragView:true },
  };
}

function _applyNetworkTheme() {
  if (!network || !nodesDS) return;
  nodesDS.update(nodesDS.get().map(n => ({ id:n.id, ..._nodeVisProps(n.type) })));
  network.setOptions(_buildOptions());
}

function _initNetwork(nodes, edges) {
  document.getElementById('emptyState').style.display = 'none';

  const visNodes = nodes.map(n => ({
    id:      n.id,
    label:   n.label,
    type:    n.type,
    rawData: n.data,
    ..._nodeVisProps(n.type),
  }));

  const visEdges = edges.map((e, i) => ({
    id:    'e' + i,
    from:  e.from,
    to:    e.to,
    label: e.label || '',
  }));

  nodesDS = new vis.DataSet(visNodes);
  edgesDS = new vis.DataSet(visEdges);

  const container = document.getElementById('network');
  if (network) network.destroy();
  network = new vis.Network(container, { nodes: nodesDS, edges: edgesDS }, _buildOptions());

  network.on('click', params => {
    if (params.nodes.length > 0) {
      const node = nodesDS.get(params.nodes[0]);
      _mostrarDetalhe(node);
    } else if (params.edges.length === 0) {
      document.getElementById('painelDetalhe').classList.add('d-none');
    }
  });

  network.once('afterDrawing', () => {
    const positions = network.getPositions();
    const ids = nodesDS.getIds();
    const allEdges = edgesDS.get();

    // 1. Reordena verticalmente dentro de cada coluna x:
    //    ADIANTAMENTO sempre no topo, demais mantêm ordem de inserção (= SEQBAIXA)
    const byLevel = {};
    ids.forEach(id => {
      const x = Math.round((positions[id]?.x ?? 0) / 5) * 5;
      if (!byLevel[x]) byLevel[x] = [];
      byLevel[x].push({ id, type: nodesDS.get(id)?.type, y: positions[id]?.y ?? 0 });
    });
    Object.values(byLevel).forEach(group => {
      if (group.length < 2 || !group.some(n => n.type === 'ADIANTAMENTO')) return;
      const ys = group.map(n => n.y).sort((a, b) => a - b);
      const sorted = [
        ...group.filter(n => n.type === 'ADIANTAMENTO').sort((a, b) => a.y - b.y),
        ...group.filter(n => n.type !== 'ADIANTAMENTO').sort((a, b) => a.y - b.y),
      ];
      sorted.forEach((n, i) => { positions[n.id].y = ys[i]; });
    });

    // 2. Alinha CONTAMOVLANAC na mesma coluna x
    const acNodes = nodesDS.get().filter(n => n.type === 'CONTAMOVLANAC');
    if (acNodes.length > 1) {
      const xs = acNodes.map(n => positions[n.id]?.x ?? 0).sort((a, b) => a - b);
      const medX = xs[Math.floor(xs.length / 2)];
      acNodes.forEach(n => { positions[n.id].x = medX; });
    }

    // 3. BFS a partir dos CONTAMOVLANAC: alinha descendentes por nível relativo
    //    Regra: filho sempre mais à frente (x maior) que o pai — válido para 1 ou N nós no nível
    if (acNodes.length > 0) {
      const acBaseX = (() => {
        const xs = acNodes.map(n => positions[n.id]?.x ?? 0).sort((a, b) => a - b);
        return xs[Math.floor(xs.length / 2)];
      })();

      const levelOf = {};
      const queue = [];
      acNodes.forEach(n => { levelOf[n.id] = 0; queue.push(n.id); });
      while (queue.length > 0) {
        const cur = queue.shift();
        allEdges.forEach(e => {
          if (e.from === cur && levelOf[e.to] === undefined) {
            levelOf[e.to] = levelOf[cur] + 1;
            queue.push(e.to);
          }
        });
      }

      const byRelLevel = {};
      Object.entries(levelOf).forEach(([id, lv]) => {
        if (lv === 0) return;
        if (!byRelLevel[lv]) byRelLevel[lv] = [];
        byRelLevel[lv].push(id);
      });

      const SEP = 270; // igual ao levelSeparation do layout hierárquico
      const levelX = { 0: acBaseX };
      const maxLv = Object.keys(byRelLevel).length ? Math.max(...Object.keys(byRelLevel).map(Number)) : 0;
      for (let lv = 1; lv <= maxLv; lv++) {
        const nodeIds = byRelLevel[lv] || [];
        // Mediana das posições atuais do nível
        let targetX = levelX[lv - 1] + SEP;
        if (nodeIds.length > 0) {
          const xs = nodeIds.map(id => positions[id]?.x ?? 0).sort((a, b) => a - b);
          const medX = xs[Math.floor(xs.length / 2)];
          // Usa a mediana só se já estiver claramente à frente do nível anterior
          if (medX > levelX[lv - 1] + 50) targetX = medX;
        }
        levelX[lv] = targetX;
        nodeIds.forEach(id => { positions[id].x = targetX; });
      }
    }

    nodesDS.update(ids.map(id => ({ id, x: positions[id]?.x, y: positions[id]?.y })));
    network.setOptions({ layout: { hierarchical: { enabled: false } } });
    network.fit({ animation: { duration:500, easingFunction:'easeInOutQuad' } });
  });

  document.getElementById('btnFit').onclick    = () => network.fit({ animation:true });
  document.getElementById('btnZoomIn').onclick  = () => network.moveTo({ scale: network.getScale() * 1.3 });
  document.getElementById('btnZoomOut').onclick = () => network.moveTo({ scale: network.getScale() / 1.3 });
}

/* ── painel de detalhe ──────────────────────────────────────────────────── */
document.getElementById('btnFecharDetalhe').addEventListener('click', () => {
  document.getElementById('painelDetalhe').classList.add('d-none');
  if (network) network.unselectAll();
});

const LABELS = {
  empresa:'Empresa', duprec:'Duplicata', duppag:'Dup. a Pagar', filial:'Filial',
  cliente:'Cliente', fornecedor:'Fornecedor',
  valor:'Valor (R$)', emissao:'Emissão', vencto:'Vencimento', quitada:'Quitada',
  userid:'Usuário', historico:'Histórico', historico2:'Histórico 2', historico3:'Histórico 3', historico4:'Histórico 4', nota:'Nota', serie:'Série',
  seqnota:'Seq. Nota (SEQNOTA)', pessoa:'Pessoa', numero:'Número', status:'Status',
  portador_desc:'Portador', nrorecibo:'Nº Recibo', nrodoc:'Nº Doc', data:'Data',
  tipoacerto:'Tipo Acerto', tiporec:'Tipo Rec.', tipopag:'Tipo Pag.', rotina:'Rotina', recibo:'Recibo', forma:'Forma de Acerto',
  estab_baixa:'Estab Baixa', estab_recibo:'Estab Recibo',
  seqrecbto:'Seq. Baixa', seqpagtodu:'Seq. Pagto', banco:'Banco', nrocheque:'Nº Cheque',
  autorizacao:'Autorização', cartao:'Cartão', tipo:'Tipo',
  numerocm:'Conta Mov.', seqcm:'Seq. CM', descricao:'Descrição', estab:'Estab', numero_:'Número',
  situacao:'Situação', vencimento:'Vencimento', representante:'Representante', analitica:'Analítica',
  nrovda:'Nº Venda', nroparcelas:'Parcelas', parcela:'Parcela',
  bandeira:'Bandeira', nrocartao:'Nº Cartão', nsu:'NSU', nomerede:'Rede',
  codcarteiradigital:'Cód. Carteira', nomecarteiradigital:'Carteira Digital', modopagamento:'Modo Pag.',
  cobcab:'Cobrança (Cab.)', cobdet:'Cobrança (Det.)',
  nome:'Nome', cnpjf:'CPF/CNPJ', tipopessoa:'Tipo Pessoa',
  endereco:'Endereço', numeroend:'Número', complemento:'Complemento',
  bairro:'Bairro', cidade:'Cidade', uf:'UF', cep:'CEP',
  telefone:'Telefone', celular:'Celular',
  portador:'Portador', bom_para:'Bom Para', favorecido:'Favorecido',
};
const SKIP = ['itens', 'portador', 'estab', 'empresa', 'pgto', 'agrfin', 'estab_recibo', 'recibo_data'];

function _mostrarDetalhe(node) {
  const painel = document.getElementById('painelDetalhe');
  painel.classList.remove('d-none');
  document.getElementById('detalheTitle').innerHTML =
    `<span class="node-badge badge-${node.type}">${node.type}</span> ${node.label.replace(/\n/g,' · ')}`;

  const d = node.rawData || {};
  let html = '<table class="detalhe-table">';
  for (const [k, v] of Object.entries(d)) {
    if (SKIP.includes(k) || v === null || v === undefined || v === '') continue;
    const lbl = LABELS[k] || k;
    let val = String(v);
    if (k === 'valor')   val = 'R$ ' + Number(v).toLocaleString('pt-BR', { minimumFractionDigits:2 });
    if (k === 'quitada') val = v === 'S' ? '<span class="text-success fw-semibold">Sim</span>'
                                         : '<span class="text-warning fw-semibold">Não</span>';
    html += `<tr><td>${lbl}</td><td>${val}</td></tr>`;
  }
  html += '</table>';

  if (node.type === 'PDUPREC') {
    html += `<hr class="my-2"/>
      <button class="btn btn-sm btn-outline-primary w-100" onclick="_testeDelphiCall()">
        <i class="bi bi-box-arrow-up-right me-1"></i>Teste ac_AbrirCadastro
      </button>`;
  }

  if (d.itens && d.itens.length > 0) {
    html += '<hr class="my-2"/><p class="small fw-semibold mb-1 text-muted">Itens da NF</p><div class="item-list">';
    for (const it of d.itens) {
      const qtd = Number(it.quantidade).toLocaleString('pt-BR', { maximumFractionDigits:3 });
      const vlr = Number(it.valor).toLocaleString('pt-BR', { minimumFractionDigits:2 });
      html += `<div class="item-row"><span>${it.descricao}</span><span>${qtd} ${it.unidade || ''} · R$ ${vlr}</span></div>`;
    }
    html += '</div>';
  }

  if (d.agrfin && d.agrfin.parcelas) {
    const af = d.agrfin;
    const fmt = v => v != null ? 'R$ ' + Number(v).toLocaleString('pt-BR', { minimumFractionDigits:2 }) : null;

    html += '<hr class="my-2"/><p class="small fw-semibold mb-1 text-muted">Acerto Financeiro</p>';

    html += '<table class="detalhe-table mb-2">';
    html += `<tr><td>Total</td><td class="fw-bold">${fmt(af.tot_valor)}</td></tr>`;
    if (af.tot_saldo_fin)   html += `<tr><td>Saldo Financeiro</td><td>${fmt(af.tot_saldo_fin)}</td></tr>`;
    if (af.tot_saldo_cm)    html += `<tr><td>Saldo Conta Mov.</td><td>${fmt(af.tot_saldo_cm)}</td></tr>`;
    if (af.tot_saldo_antec) html += `<tr><td>Saldo Antecipado</td><td>${fmt(af.tot_saldo_antec)}</td></tr>`;
    if (af.tot_bonif)       html += `<tr><td>Bonificação</td><td>${fmt(af.tot_bonif)}</td></tr>`;
    if (af.tot_juro)        html += `<tr><td>Juros</td><td>${fmt(af.tot_juro)}</td></tr>`;
    html += '</table>';

    html += '<div class="item-list">';
    for (const p of af.parcelas) {
      const quitada = p.quitada === 'S'
        ? '<span class="text-success fw-semibold">Quitada</span>'
        : '<span class="text-warning fw-semibold">Em aberto</span>';
      html += `<div class="item-row" style="flex-direction:column;align-items:flex-start;gap:2px;padding:6px 0;">
        <div class="d-flex justify-content-between w-100">
          <span class="fw-semibold">Parc. ${p.seq} · ${p.forma}</span>
          <span>${fmt(p.valor)}</span>
        </div>
        <div class="d-flex justify-content-between w-100 text-muted" style="font-size:0.72rem;">
          <span>Dup. ${p.duprec || ''} · Venc. ${p.vencto || ''}</span>
          <span>${quitada}</span>
        </div>
      </div>`;
    }
    html += '</div>';
  }

  if (d.recibo_data) {
    const rb = d.recibo_data;
    const numLabel = rb.numero_esp || rb.numero;
    html += `<hr class="my-2"/>
      <button class="btn btn-sm btn-outline-secondary w-100"
        onclick="_abrirRecibo(this)" data-recibo='${JSON.stringify(rb).replace(/'/g,"&#39;")}'>
        <i class="bi bi-receipt me-1"></i>Ver Recibo Nº ${numLabel}
      </button>`;
  }

  if (d.pgto && d.pgto.parcelas) {
    const pg = d.pgto;
    const fmt = v => v != null ? 'R$ ' + Number(v).toLocaleString('pt-BR', { minimumFractionDigits:2 }) : null;

    html += '<hr class="my-2"/><p class="small fw-semibold mb-1 text-muted">Acerto Financeiro</p>';

    // Totalizadores
    html += '<table class="detalhe-table mb-2">';
    html += `<tr><td>Total</td><td class="fw-bold">${fmt(pg.tot_valor)}</td></tr>`;
    if (pg.tot_saldo_fin)   html += `<tr><td>Saldo Financeiro</td><td>${fmt(pg.tot_saldo_fin)}</td></tr>`;
    if (pg.tot_saldo_cm)    html += `<tr><td>Saldo Conta Mov.</td><td>${fmt(pg.tot_saldo_cm)}</td></tr>`;
    if (pg.tot_saldo_antec) html += `<tr><td>Saldo Antecipado</td><td>${fmt(pg.tot_saldo_antec)}</td></tr>`;
    if (pg.tot_bonif)       html += `<tr><td>Bonificação</td><td>${fmt(pg.tot_bonif)}</td></tr>`;
    if (pg.tot_juro)        html += `<tr><td>Juros</td><td>${fmt(pg.tot_juro)}</td></tr>`;
    html += '</table>';

    // Parcelas
    html += '<div class="item-list">';
    for (const p of pg.parcelas) {
      html += `<div class="item-row" style="flex-direction:column;align-items:flex-start;gap:2px;padding:6px 0;">
        <div class="d-flex justify-content-between w-100">
          <span class="fw-semibold">Parc. ${p.seq} · ${p.forma}</span>
          <span>${fmt(p.valor)}</span>
        </div>
        <div class="d-flex justify-content-between w-100 text-muted" style="font-size:0.72rem;">
          <span>${p.prazo || ''}</span>
          <span>${p.situacao || ''}</span>
        </div>
      </div>`;
    }
    html += '</div>';
  }

  document.getElementById('detalheBody').innerHTML = html;
}

/* ── submit ──────────────────────────────────────────────────────────────── */
document.getElementById('formConsulta').addEventListener('submit', async e => {
  e.preventDefault();
  const tela    = selTela.value;
  const empresa = document.getElementById('inpEmpresa').value;
  const estab   = document.getElementById('inpEstab').value;
  const serie   = document.getElementById('inpSerie').value;
  const doc     = document.getElementById('inpDoc').value.trim();
  const status  = document.getElementById('areaStatus');
  if (!doc) return;

  status.innerHTML = '<span class="text-muted small"><i class="bi bi-arrow-clockwise spin me-1"></i>Consultando...</span>';
  document.getElementById('painelDetalhe').classList.add('d-none');

  const p = new URLSearchParams({ tela, doc });
  if (tela === 'DUPREC' || tela === 'DUPPAG') {
    p.set('empresa', empresa);
  } else if (tela === 'CONTAMOV') {
    p.set('numerocm', empresa);  // inpEmpresa reaproveitado para Nº CM
    p.set('estab', estab);
  } else {
    p.set('estab', estab);
  }
  if (tela === 'PEDCAB') p.set('serie', serie);

  try {
    const res  = await fetch('/api/trace?' + p);
    const data = await res.json();
    if (!res.ok || data.erro) {
      status.innerHTML = `<span class="text-danger small"><i class="bi bi-exclamation-triangle me-1"></i>${data.erro || 'Erro'}</span>`;
      return;
    }
    _initNetwork(data.nodes, data.edges);
    status.innerHTML = `<span class="text-success small"><i class="bi bi-check-circle me-1"></i>${data.nodes.length} nós · ${data.edges.length} conexões</span>`;
  } catch (err) {
    status.innerHTML = `<span class="text-danger small"><i class="bi bi-exclamation-triangle me-1"></i>${err.message}</span>`;
  }
});

/* ── modal recibo ────────────────────────────────────────────────────────── */
let _modalRecibo = null;
function _abrirRecibo(btn) {
  const rb = JSON.parse(btn.dataset.recibo);
  const fmt = v => 'R$ ' + Number(v).toLocaleString('pt-BR', { minimumFractionDigits:2 });
  const numLabel = rb.numero_esp || rb.numero;

  document.getElementById('modalReciboTitulo').textContent = `Recibo Nº ${numLabel}`;

  let h = '';

  // Cabeçalho
  h += `<div style="display:flex;justify-content:space-between;align-items:flex-start;border-bottom:1px solid var(--bs-border-color);padding-bottom:8px;margin-bottom:12px;">
    <div style="font-size:1.4rem;font-weight:700;letter-spacing:2px;">RECIBO</div>
    <div style="text-align:right;">
      <div style="font-size:0.75rem;">Número: <strong>${numLabel}</strong></div>
      <div style="font-size:1.1rem;font-weight:700;">${fmt(rb.valor)}</div>
    </div>
  </div>`;

  // Devedor
  if (rb.nomedevedor) {
    h += `<div style="margin-bottom:6px;">Recebemos do Sr.(a) <strong>${rb.nomedevedor}</strong></div>`;
  }
  h += `<div style="margin-bottom:12px;">a importância de <strong>${fmt(rb.valor)}</strong></div>`;

  // Referente
  if (rb.referente) {
    h += `<div style="margin-bottom:4px;font-weight:600;font-size:0.8rem;">Referente à</div>`;
    h += _renderReferente(rb.referente);
  }

  // Rodapé
  h += `<div style="border-top:1px solid var(--bs-border-color);margin-top:16px;padding-top:12px;">`;
  h += `<div style="margin-bottom:8px;">Para maior clareza, firmamos o presente.</div>`;
  if (rb.data) {
    h += `<div style="text-align:right;margin-bottom:12px;">${rb.data}</div>`;
  }
  if (rb.nomeemitente) {
    h += `<div>Emitente: <strong>${rb.nomeemitente}</strong></div>`;
  }
  if (rb.endemitente) h += `<div>Endereço: ${rb.endemitente}</div>`;
  if (rb.compemitente) h += `<div>${rb.compemitente}</div>`;
  if (rb.cnpjf)       h += `<div>CPF/CNPJ: ${rb.cnpjf}</div>`;
  if (rb.usuario)     h += `<div style="margin-top:8px;font-size:0.72rem;color:var(--bs-secondary-color);">Usuário: ${rb.usuario}</div>`;
  h += '</div>';

  document.getElementById('modalReciboBody').innerHTML = h;

  if (!_modalRecibo) _modalRecibo = new bootstrap.Modal(document.getElementById('modalRecibo'));
  _modalRecibo.show();
}

/* ── teste de chamada Delphi ─────────────────────────────────────────────── */
function _testeDelphiCall() {
  try {
    window.delphiApp.call('PDUPREC', { id: 42 });
  } catch (e) {
    alert('Erro ao chamar delphiApp.call:\n' + e.message);
  }
}

/* ── integração Delphi: lê window.delphiApp.params e auto-preenche ──────── */
function _parseClave(chave) {
  // extrai TABLE.COLUNA = 'valor' de qualquer string WHERE
  const result = {};
  const re = /\w+\.(\w+)\s*=\s*'([^']*)'/g;
  let m;
  while ((m = re.exec(chave)) !== null) {
    result[m[1].toUpperCase()] = m[2];
  }
  return result;
}

function _initFromERP() {
  const TELA_MAP = { PDUPREC: 'DUPREC', PDUPPAGA: 'DUPPAG', NFCAB: 'NFCAB', PEDCAB: 'PEDCAB', CONTAMOVLAN: 'CONTAMOV' };

  function tentar() {
    const params = window.delphiApp?.params;
    if (!params?.TIPODOC || !params?.CHAVE) return false;

    const tela = TELA_MAP[params.TIPODOC.toUpperCase()];
    if (!tela) return false;

    const kv = _parseClave(params.CHAVE);

    selTela.value = tela;
    _adaptarCampos();

    if (tela === 'DUPREC') {
      document.getElementById('inpEmpresa').value = kv.EMPRESA || 1;
      document.getElementById('inpDoc').value     = kv.DUPREC  || '';
    } else if (tela === 'DUPPAG') {
      document.getElementById('inpEmpresa').value = kv.EMPRESA || 1;
      document.getElementById('inpDoc').value     = kv.DUPPAG  || '';
    } else if (tela === 'NFCAB') {
      document.getElementById('inpEstab').value = kv.ESTAB   || 1;
      document.getElementById('inpDoc').value   = kv.SEQNOTA || '';
    } else if (tela === 'PEDCAB') {
      document.getElementById('inpEstab').value = kv.ESTAB  || 1;
      document.getElementById('inpSerie').value = kv.SERIE  || '';
      document.getElementById('inpDoc').value   = kv.NUMERO || '';
    } else if (tela === 'CONTAMOV') {
      document.getElementById('inpEmpresa').value = kv.NUMEROCM || '';
      document.getElementById('inpEstab').value   = kv.ESTAB    || 1;
      document.getElementById('inpDoc').value     = kv.SEQCM    || '';
    }

    if (document.getElementById('inpDoc').value) {
      document.getElementById('formConsulta').dispatchEvent(new Event('submit'));
    }
    return true;
  }

  if (tentar()) return;
  let t = 0;
  const iv = setInterval(() => {
    t++;
    if (tentar() || t >= 19) clearInterval(iv);
  }, 80);
}

/* ── init ────────────────────────────────────────────────────────────────── */
_adaptarCampos();
_initFromERP();

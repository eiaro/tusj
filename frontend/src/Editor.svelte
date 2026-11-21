<script>
  // Label editor: place text, QR codes, icons and boxes on a label of a fixed size, then publish
  // it as a label type. The picture on the canvas is drawn by the backend with the same code
  // that prints, so it is exactly what comes out; the outlines on top are only for editing.
  import { deleteDesign, designValues, getDesignMeta, getDesigns, previewDesign, saveDesign, searchDesignSource } from './api.js'
  import EditorData from './EditorData.svelte'
  import EditorFields from './EditorFields.svelte'
  import { LOCALES, errorText, i18n, pick, t } from './i18n.svelte.js'

  const languages = Object.keys(LOCALES)
  const SNAP = 0.5 // mm
  const MIN_SIZE = 1 // mm

  let meta = $state(null)
  let designs = $state([])
  let loadError = $state(null)

  let design = $state(null) // the design being edited (without id)
  let designId = $state('')
  let isNew = $state(false)
  let savedJson = $state('')
  let selectedId = $state(null)
  let saving = $state(false)
  let message = $state(null) // {ok, text}
  let confirmingDelete = $state(false)

  let zoom = $state(10) // screen px per mm
  let testValues = $state({})

  let previewUrl = $state('')
  let currentValues = $state({}) // placeholder -> text shown on the label right now
  let previewError = $state(null)

  Promise.all([getDesignMeta(), getDesigns()])
    .then(([m, d]) => {
      meta = m
      designs = d
    })
    .catch((e) => (loadError = e))

  // --- Derived ---

  const media = $derived(meta && design ? meta.media.find((m) => m.id === design.media) : null)
  const frame = $derived.by(() => {
    if (!media) return { w: 50, h: 30 }
    const across = media.printable_mm
    const along = media.endless ? Number(design.length_mm) || 30 : media.length_mm
    return design.orientation === 'landscape' ? { w: along, h: across } : { w: across, h: along }
  })
  const selected = $derived(design?.elements.find((e) => e.id === selectedId) ?? null)
  const source = $derived(design?.source ? meta?.sources.find((s) => s.id === design.source) : null)
  const dirty = $derived(design != null && JSON.stringify(design) !== savedJson)
  const mediaChoices = $derived(
    (meta?.media ?? []).toSorted((a, b) => (b.endless - a.endless) || a.tape_mm - b.tape_mm || (a.length_mm ?? 0) - (b.length_mm ?? 0)),
  )

  // Placeholders the selected element can use.
  const placeholders = $derived([
    ...(design?.fields ?? []).map((f) => ({ key: f.id, label: pick(f.label) || f.id })),
    ...(source?.variables ?? []).map((v) => ({ key: `${source.key}.${v.id}`, label: pick(v.label) })),
    { key: 'today', label: t('editor.placeholders.today') },
  ])

  function mediaLabel(m) {
    return m.endless
      ? `${m.tape_mm} mm ${t('editor.design.endless')}`
      : `${m.tape_mm} × ${m.length_mm.toFixed(0)} mm ${t('editor.design.dieCut')}`
  }

  // --- Opening, saving ---

  function open(d, asNew = false) {
    const { id, ...rest } = structuredClone($state.snapshot(d))
    rest.elements = (rest.elements ?? []).map((e) => ({ ...e, id: e.id ?? uid() }))
    rest.fields = (rest.fields ?? []).map((f) => ({ ...f, label: asMap(f.label) }))
    rest.name = asMap(rest.name)
    design = rest
    designId = asNew ? '' : id
    isNew = asNew
    savedJson = asNew ? '' : JSON.stringify(rest)
    selectedId = null
    testValues = {}
    message = null
    confirmingDelete = false
    resetHistory()
  }

  function asMap(text) {
    if (text && typeof text === 'object') return { ...Object.fromEntries(languages.map((l) => [l, ''])), ...text }
    return Object.fromEntries(languages.map((l) => [l, text ?? '']))
  }

  function newDesign() {
    open({
      id: '',
      name: { en: '', nb: '' },
      icon: '🏷️',
      media: '62',
      length_mm: 29,
      orientation: 'portrait',
      source: null,
      fields: [{ id: 'title', type: 'text', label: { en: 'Title', nb: 'Tittel' }, required: true }],
      elements: [
        { type: 'text', x: 3, y: 3, w: 52.9, h: 12, text: '{title}', size: 20, bold: true, align: 'left', valign: 'top', fit: 'shrink' },
      ],
    }, true)
  }

  const slug = (s) => (s ?? '').toLowerCase().normalize('NFKD').replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 64)

  const idOk = $derived(/^[a-z0-9][a-z0-9_-]{0,63}$/.test(designId))

  async function publish() {
    if (!languages.some((l) => design.name[l]?.trim())) {
      message = { ok: false, text: t('editor.design.nameNeeded') }
      return
    }
    if (isNew && !designId) designId = slug(pick(design.name))
    if (!idOk) {
      message = { ok: false, text: t('editor.design.idHint', { id: designId || '…' }) }
      return
    }
    if (isNew && designs.some((d) => d.id === designId)) {
      message = { ok: false, text: t('editor.design.idTaken', { id: designId }) }
      return
    }
    saving = true
    message = null
    try {
      const body = $state.snapshot(design)
      const saved = await saveDesign(designId, body)
      savedJson = JSON.stringify(design)
      isNew = false
      const i = designs.findIndex((d) => d.id === saved.id)
      if (i >= 0) designs[i] = saved
      else designs.push(saved)
      message = { ok: true, text: t('editor.published') }
    } catch (e) {
      message = { ok: false, text: errorText(e) }
    } finally {
      saving = false
    }
  }

  async function remove() {
    if (!confirmingDelete) {
      confirmingDelete = true
      return
    }
    try {
      if (!isNew) await deleteDesign(designId)
      designs = designs.filter((d) => d.id !== designId)
      design = null
    } catch (e) {
      message = { ok: false, text: errorText(e) }
    } finally {
      confirmingDelete = false
    }
  }

  // --- Preview: drawn by the backend shortly after each change ---

  let previewSeq = 0
  $effect(() => {
    if (!design) return
    const body = $state.snapshot(design)
    const values = $state.snapshot(testValues)
    const lang = i18n.locale
    const seq = ++previewSeq
    const timer = setTimeout(async () => {
      try {
        const [blob, vals] = await Promise.all([
          previewDesign(body, values, lang),
          designValues(body, values, lang).catch(() => null),
        ])
        if (seq !== previewSeq) return
        if (vals) currentValues = vals
        if (previewUrl) URL.revokeObjectURL(previewUrl)
        previewUrl = URL.createObjectURL(blob)
        previewError = null
      } catch (e) {
        if (seq === previewSeq) previewError = e
      }
    }, 120)
    return () => clearTimeout(timer)
  })

  // --- Undo / redo: snapshots taken when editing pauses ---

  let past = []
  let future = []
  let current = ''
  let historyTick = $state(0)
  let dragging = $state(false)

  function resetHistory() {
    past = []
    future = []
    current = JSON.stringify(design)
    historyTick++
  }

  $effect(() => {
    if (!design || dragging) return
    const snap = JSON.stringify(design)
    const timer = setTimeout(() => {
      if (snap === current) return
      past.push(current)
      current = snap
      future = []
      historyTick++
    }, 300)
    return () => clearTimeout(timer)
  })

  function undo() {
    if (!past.length) return
    future.push(current)
    current = past.pop()
    design = JSON.parse(current)
    historyTick++
  }

  function redo() {
    if (!future.length) return
    past.push(current)
    current = future.pop()
    design = JSON.parse(current)
    historyTick++
  }

  const canUndo = $derived((historyTick, past.length > 0))
  const canRedo = $derived((historyTick, future.length > 0))

  // --- Elements ---

  let counter = 0
  const uid = () => `e${Date.now().toString(36)}${(counter++).toString(36)}`

  function add(kind) {
    const w = Math.min(30, frame.w - 4)
    const base = { id: uid(), x: 2, y: 2 }
    const el = {
      text: { ...base, type: 'text', w, h: 8, text: t('editor.add.sampleText'), size: 14, bold: false, align: 'left', valign: 'top', fit: 'shrink' },
      qr: { ...base, type: 'qr', w: 20, h: 20, data: source ? `{${source.key}.barcode}` : 'https://' },
      symbol: { ...base, type: 'symbol', w: 10, h: 10, value: 'mdi:star' },
      rect: { ...base, type: 'rect', w, h: 10, stroke: 0.5, radius: 1, fill: false },
      line: { ...base, type: 'rect', w, h: 0.4, stroke: 0, radius: 0, fill: true },
    }[kind]
    design.elements.push(el)
    selectedId = el.id
  }

  // --- Data dragged or clicked in from the data panel ---

  const isCode = (key) => /\.(barcode|qr|url)$/.test(key)

  function dataElement(key, x, y, w = null) {
    const token = `{${key}}`
    const el = isCode(key)
      ? { id: uid(), type: 'qr', w: 15, h: 15, data: token }
      : { id: uid(), type: 'text', w: 30, h: 6, text: token, size: 12, bold: false, align: 'left', valign: 'top', fit: 'shrink' }
    el.w = Math.max(MIN_SIZE, Math.min(w ?? el.w, frame.w - 2))
    el.h = Math.max(MIN_SIZE, Math.min(el.h, frame.h - 2))
    const snap = (v) => round(Math.round(v / SNAP) * SNAP)
    el.x = snap(Math.max(0, Math.min(x, frame.w - el.w)))
    el.y = snap(Math.max(0, Math.min(y, frame.h - el.h)))
    design.elements.push(el)
    selectedId = el.id
  }

  function appendTo(el, key) {
    const token = `{${key}}`
    const join = (s) => (s ? `${s} ${token}` : token)
    if (el.type === 'text') {
      if (el.text && typeof el.text === 'object') for (const lang of Object.keys(el.text)) el.text[lang] = join(el.text[lang])
      else el.text = join(el.text)
    } else if (el.type in contentKey) {
      el[contentKey[el.type]] = token // a QR code or icon shows one thing
    }
    selectedId = el.id
  }

  // Click in the data panel: into the field being edited, else the selected element, else a new
  // element below the others.
  function useData(key) {
    if (selected && selected.type !== 'rect') {
      if (target && document.contains(target.node)) insert(key)
      else appendTo(selected, key)
      return
    }
    const spot = freeSpot(isCode(key) ? 15 : 30, isCode(key) ? 15 : 6)
    dataElement(key, spot.x, spot.y, spot.w)
  }

  // The first place (top to bottom, left to right) where a w × h mm box overlaps nothing but
  // boxes and lines (often a frame round the whole label); the middle if the label is full.
  function freeSpot(w, h) {
    const others = design.elements.filter((e) => e.type !== 'rect')
    const free = (x, y, bw) => others.every((e) => x + bw <= e.x || x >= e.x + e.w || y + h <= e.y || y >= e.y + e.h)
    for (const bw of [w, w / 2]) { // a narrower box (text shrinks to fit) before giving up
      for (let y = 1; y + h <= frame.h - 1; y += SNAP) {
        for (let x = 1; x + bw <= frame.w - 1; x += SNAP) {
          if (free(x, y, bw)) return { x, y, w: bw }
        }
      }
    }
    return { x: Math.max(0, (frame.w - w) / 2), y: Math.max(0, (frame.h - h) / 2), w }
  }

  const DATA_TYPE = 'application/x-tusj-placeholder'
  let dropping = $state(false)

  function dragOver(e) {
    if (!e.dataTransfer.types.includes(DATA_TYPE)) return
    e.preventDefault()
    e.dataTransfer.dropEffect = 'copy'
    dropping = true
  }

  function drop(e) {
    dropping = false
    const key = e.dataTransfer.getData(DATA_TYPE)
    if (!key) return
    e.preventDefault()
    const rect = e.currentTarget.getBoundingClientRect()
    const x = (e.clientX - rect.left) / zoom
    const y = (e.clientY - rect.top) / zoom
    // Dropped on a text element (topmost first): add to it. Elsewhere: a new element there.
    const hit = design.elements.findLast((el) => el.type !== 'rect' && x >= el.x && x <= el.x + el.w && y >= el.y && y <= el.y + el.h)
    if (hit) appendTo(hit, key)
    else dataElement(key, x, y)
  }

  function removeSelected() {
    design.elements = design.elements.filter((e) => e.id !== selectedId)
    selectedId = null
  }

  function duplicateSelected() {
    const copy = { ...structuredClone($state.snapshot(selected)), id: uid() }
    copy.x += 2
    copy.y += 2
    design.elements.push(copy)
    selectedId = copy.id
  }

  function move(step) {
    const i = design.elements.findIndex((e) => e.id === selectedId)
    const j = i + step
    if (i < 0 || j < 0 || j >= design.elements.length) return
    const [el] = design.elements.splice(i, 1)
    design.elements.splice(j, 0, el)
  }

  const round = (v) => Math.round(v * 100) / 100
  const snap = (v, free) => (free ? round(v) : Math.round(v / SNAP) * SNAP)

  // --- Dragging and resizing on the canvas ---

  let drag = null

  function startDrag(e, el, handle = null) {
    if (e.button !== 0) return
    e.preventDefault()
    e.stopPropagation()
    selectedId = el.id
    drag = { el, handle, x: e.clientX, y: e.clientY, orig: { x: el.x, y: el.y, w: el.w, h: el.h } }
    dragging = true
    window.addEventListener('pointermove', onDrag)
    window.addEventListener('pointerup', endDrag, { once: true })
  }

  function onDrag(e) {
    if (!drag) return
    const dx = (e.clientX - drag.x) / zoom
    const dy = (e.clientY - drag.y) / zoom
    const { el, handle, orig } = drag
    const free = e.altKey
    if (!handle) {
      el.x = snap(orig.x + dx, free)
      el.y = snap(orig.y + dy, free)
      return
    }
    if (handle.includes('e')) el.w = Math.max(MIN_SIZE, snap(orig.w + dx, free))
    if (handle.includes('s')) el.h = Math.max(MIN_SIZE, snap(orig.h + dy, free))
    if (handle.includes('w')) {
      const x = Math.min(snap(orig.x + dx, free), orig.x + orig.w - MIN_SIZE)
      el.w = round(orig.w + orig.x - x)
      el.x = x
    }
    if (handle.includes('n')) {
      const y = Math.min(snap(orig.y + dy, free), orig.y + orig.h - MIN_SIZE)
      el.h = round(orig.h + orig.y - y)
      el.y = y
    }
  }

  function endDrag() {
    window.removeEventListener('pointermove', onDrag)
    drag = null
    dragging = false
  }

  // --- Keyboard ---

  function onKey(e) {
    if (!design) return
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)
    const mod = e.ctrlKey || e.metaKey
    if (mod && e.key.toLowerCase() === 'z' && !typing) {
      e.preventDefault()
      e.shiftKey ? redo() : undo()
    } else if (mod && e.key.toLowerCase() === 'y' && !typing) {
      e.preventDefault()
      redo()
    } else if (mod && e.key.toLowerCase() === 's') {
      e.preventDefault()
      publish()
    } else if (typing || !selected) {
      return
    } else if (mod && e.key.toLowerCase() === 'd') {
      e.preventDefault()
      duplicateSelected()
    } else if (e.key === 'Delete' || e.key === 'Backspace') {
      e.preventDefault()
      removeSelected()
    } else if (e.key === 'Escape') {
      selectedId = null
    } else if (e.key.startsWith('Arrow')) {
      e.preventDefault()
      const step = e.shiftKey ? 2 : SNAP
      if (e.key === 'ArrowLeft') selected.x = round(selected.x - step)
      if (e.key === 'ArrowRight') selected.x = round(selected.x + step)
      if (e.key === 'ArrowUp') selected.y = round(selected.y - step)
      if (e.key === 'ArrowDown') selected.y = round(selected.y + step)
    }
  }

  // --- Text and placeholders ---

  // The input that last had focus, so a placeholder chip inserts where the cursor is.
  let target = null
  function track(e, apply) {
    target = { node: e.currentTarget, apply }
  }

  function insert(key) {
    const token = `{${key}}`
    if (!target || !document.contains(target.node)) return
    const node = target.node
    const start = node.selectionStart ?? node.value.length
    const end = node.selectionEnd ?? start
    const value = node.value.slice(0, start) + token + node.value.slice(end)
    target.apply(value)
    requestAnimationFrame(() => {
      node.focus()
      node.setSelectionRange(start + token.length, start + token.length)
    })
  }

  const perLanguage = (el) => el.text != null && typeof el.text === 'object'

  function setPerLanguage(el, on) {
    el.text = on
      ? Object.fromEntries(languages.map((l) => [l, el.text ?? '']))
      : (el.text[i18n.locale] ?? Object.values(el.text)[0] ?? '')
  }

  const contentKey = { qr: 'data', symbol: 'value' }

  // Placeholders an element uses that nothing fills in: printed as typed, so warn about them.
  function unknownPlaceholders(el) {
    const raw = el.type === 'text' ? el.text : el[contentKey[el.type]]
    const texts = raw && typeof raw === 'object' ? Object.values(raw) : [raw ?? '']
    const known = new Set(placeholders.map((p) => p.key))
    const keys = texts.flatMap((s) => [...String(s).matchAll(/\{([a-zA-Z_][\w.]*)\}/g)].map((m) => m[1]))
    return [...new Set(keys.filter((k) => !known.has(k)))]
  }
  const unknown = $derived(selected ? unknownPlaceholders(selected) : [])

</script>

<svelte:window onkeydown={onKey} />

<div class="editor">
  <aside class="list">
    <button type="button" class="primary" onclick={newDesign}>+ {t('editor.new')}</button>
    {#if loadError}
      <p class="error">{errorText(loadError)}</p>
    {:else if !designs.length}
      <p class="muted">{t('editor.empty')}</p>
    {/if}
    <ul>
      {#each designs as d (d.id)}
        <li>
          <button type="button" class:on={!isNew && design && d.id === designId} onclick={() => open(d)}>
            <span aria-hidden="true">{d.icon}</span> {pick(d.name)}
          </button>
        </li>
      {/each}
    </ul>
    {#if design}
      <EditorData {design} {source} sources={meta?.sources ?? []} values={currentValues}
                  bind:testValues search={(q, lang) => searchDesignSource(source.id, q, lang)} onuse={useData}
                  onsource={(id) => (design.source = id)} />
    {/if}
  </aside>

  {#if !design}
    <section class="blank">
      <p class="muted">{t('editor.intro')}</p>
    </section>
  {:else}
    <section class="stage">
      <div class="toolbar" role="toolbar">
        {#each ['text', 'qr', 'symbol', 'rect', 'line'] as kind}
          <button type="button" onclick={() => add(kind)}>+ {t(`editor.add.${kind}`)}</button>
        {/each}
        <span class="spacer"></span>
        <button type="button" disabled={!canUndo} onclick={undo} title="Ctrl+Z">↶ {t('editor.undo')}</button>
        <button type="button" disabled={!canRedo} onclick={redo} title="Ctrl+Shift+Z">↷ {t('editor.redo')}</button>
        <label class="zoom">🔍 <input type="range" min="4" max="24" step="1" bind:value={zoom} /></label>
      </div>

      <div class="canvas-wrap">
        <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
        <div class="canvas" class:dropping style:width="{frame.w * zoom}px" style:height="{frame.h * zoom}px"
             onpointerdown={() => (selectedId = null)}
             ondragover={dragOver} ondragleave={() => (dropping = false)} ondrop={drop}>
          {#if previewUrl}<img src={previewUrl} alt={t('preview.alt')} draggable="false" />{/if}
          {#each design.elements as el (el.id)}
            <!-- svelte-ignore a11y_no_static_element_interactions -->
            <div class="box" class:selected={el.id === selectedId} class:unknown={unknownPlaceholders(el).length > 0}
                 style:left="{el.x * zoom}px" style:top="{el.y * zoom}px"
                 style:width="{el.w * zoom}px" style:height="{el.h * zoom}px"
                 onpointerdown={(e) => startDrag(e, el)}>
              {#if el.id === selectedId}
                {#each ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w'] as h}
                  <span class="handle {h}" onpointerdown={(e) => startDrag(e, el, h)}></span>
                {/each}
              {/if}
            </div>
          {/each}
        </div>
        <p class="dims muted">
          {t('editor.design.size', { w: frame.w.toFixed(1), h: frame.h.toFixed(1) })}
          {#if media} · {mediaLabel(media)}{/if}
        </p>
        {#if previewError}<p class="error">{errorText(previewError)}</p>{/if}
        <p class="muted hint">{t('editor.keys')}</p>
      </div>

      <div class="publish-bar">
        {#if message}<span class:error={!message.ok} class:ok={message.ok}>{message.text}</span>
        {:else if dirty}<span class="muted">{t('editor.unsaved')}</span>{/if}
        <span class="spacer"></span>
        <button type="button" class="danger-btn" onclick={remove} onblur={() => (confirmingDelete = false)}>
          {confirmingDelete ? t('editor.confirmDelete') : t('editor.delete')}
        </button>
        <button type="button" class="primary" disabled={saving || (!dirty && !isNew)} onclick={publish}>
          {saving ? t('editor.publishing') : t('editor.publish')}
        </button>
      </div>
    </section>

    <aside class="props">
      {#if selected}
        <div class="props-head">
          <h2>{t(`editor.element.${selected.type}`)}</h2>
          <button type="button" class="link" onclick={() => (selectedId = null)}>{t('editor.backToLabel')}</button>
        </div>

        {#if selected.type === 'text'}
          {#if perLanguage(selected)}
            {#each languages as lang}
              <label>{t('editor.props.text')} ({lang})
                <textarea rows="2" value={selected.text[lang] ?? ''}
                          onfocus={(e) => track(e, (v) => (selected.text[lang] = v))}
                          oninput={(e) => (selected.text[lang] = e.currentTarget.value)}></textarea>
              </label>
            {/each}
          {:else}
            <label>{t('editor.props.text')}
              <textarea rows="2" value={selected.text ?? ''}
                        onfocus={(e) => track(e, (v) => (selected.text = v))}
                        oninput={(e) => (selected.text = e.currentTarget.value)}></textarea>
            </label>
          {/if}
          <label class="check"><input type="checkbox" checked={perLanguage(selected)}
                 onchange={(e) => setPerLanguage(selected, e.currentTarget.checked)} /> {t('editor.props.perLanguage')}</label>
        {:else if selected.type in contentKey}
          <label>{t(`editor.props.${contentKey[selected.type]}`)}
            <input value={selected[contentKey[selected.type]] ?? ''} spellcheck="false"
                   onfocus={(e) => track(e, (v) => (selected[contentKey[selected.type]] = v))}
                   oninput={(e) => (selected[contentKey[selected.type]] = e.currentTarget.value)} />
          </label>
          {#if selected.type === 'symbol'}<p class="muted small">{t('editor.props.valueHint')}</p>{/if}
        {/if}

        {#if unknown.length}
          <p class="warn">{t('editor.placeholders.unknown', { names: unknown.map((k) => `{${k}}`).join(', ') })}</p>
        {/if}

        {#if selected.type !== 'rect'}
          <div class="chips-head">{t('editor.placeholders.heading')}</div>
          <div class="placeholders">
            {#each placeholders as p (p.key)}
              <button type="button" class="ph" title={`{${p.key}}`} onpointerdown={(e) => e.preventDefault()}
                      onclick={() => insert(p.key)}>{p.label}</button>
            {/each}
          </div>
        {/if}

        {#if selected.type === 'text'}
          <div class="grid2">
            <label>{t('editor.props.size')}<input type="number" min="4" max="300" step="0.5" bind:value={selected.size} /></label>
            <label class="check pad"><input type="checkbox" bind:checked={selected.bold} /> {t('editor.props.bold')}</label>
          </div>
          <div class="seg" role="group" aria-label={t('editor.props.align')}>
            {#each [['left', '⇤'], ['center', '↔'], ['right', '⇥']] as [v, icon]}
              <button type="button" class:on={selected.align === v} title={t(`editor.props.${v}`)} onclick={() => (selected.align = v)}>{icon}</button>
            {/each}
            {#each [['top', '⤒'], ['middle', '↕'], ['bottom', '⤓']] as [v, icon]}
              <button type="button" class:on={selected.valign === v} title={t(`editor.props.${v}`)} onclick={() => (selected.valign = v)}>{icon}</button>
            {/each}
          </div>
          <label>{t('editor.props.fit')}
            <select bind:value={selected.fit}>
              <option value="shrink">{t('editor.props.fitShrink')}</option>
              <option value="none">{t('editor.props.fitNone')}</option>
            </select>
          </label>
        {:else if selected.type === 'rect'}
          <div class="grid2">
            <label>{t('editor.props.stroke')}<input type="number" min="0" max="20" step="0.1" bind:value={selected.stroke} /></label>
            <label>{t('editor.props.radius')}<input type="number" min="0" max="50" step="0.5" bind:value={selected.radius} /></label>
          </div>
          <label class="check"><input type="checkbox" bind:checked={selected.fill} /> {t('editor.props.fill')}</label>
        {/if}

        <div class="grid4">
          {#each ['x', 'y', 'w', 'h'] as k}
            <label>{t(`editor.props.${k}`)}<input type="number" step="0.5" bind:value={selected[k]} /></label>
          {/each}
        </div>

        <div class="actions-row">
          <button type="button" onclick={() => move(1)}>{t('editor.props.forward')}</button>
          <button type="button" onclick={() => move(-1)}>{t('editor.props.backward')}</button>
          <button type="button" onclick={duplicateSelected}>{t('editor.props.duplicate')}</button>
          <button type="button" class="danger-btn" onclick={removeSelected}>{t('editor.props.remove')}</button>
        </div>
      {:else}
        <h2>{t('editor.design.heading')}</h2>
        {#each languages as lang}
          <label>{t('editor.design.name')} ({lang})<input bind:value={design.name[lang]} /></label>
        {/each}
        <div class="grid2">
          <label>{t('editor.design.icon')}<input bind:value={design.icon} maxlength="8" /></label>
          <label>{t('editor.design.id')}
            <input class="mono" value={designId} disabled={!isNew} spellcheck="false"
                   placeholder={slug(pick(design.name)) || 'my-label'} oninput={(e) => (designId = e.currentTarget.value)} />
          </label>
        </div>
        {#if isNew}<p class="muted small">{t('editor.design.idHint', { id: designId || slug(pick(design.name)) || '…' })}</p>{/if}

        <label>{t('editor.design.media')}
          <select bind:value={design.media}
                  onchange={() => { if (media?.endless && !design.length_mm) design.length_mm = 29; if (!media?.endless) delete design.length_mm }}>
            {#each mediaChoices as m (m.id)}<option value={m.id}>{mediaLabel(m)}</option>{/each}
          </select>
        </label>
        <div class="grid2">
          {#if media?.endless}
            <label>{t('editor.design.length')}<input type="number" min="5" max="1000" step="1" bind:value={design.length_mm} /></label>
          {/if}
          <label>{t('editor.design.orientation')}
            <select bind:value={design.orientation}>
              <option value="portrait">{t('editor.design.portrait')}</option>
              <option value="landscape">{t('editor.design.landscape')}</option>
            </select>
          </label>
        </div>

        <h3>{t('editor.fields.heading')}</h3>
        <EditorFields bind:fields={design.fields} types={meta?.field_types ?? []} />
      {/if}
    </aside>
  {/if}
</div>

<style>
  .editor {
    display: grid;
    grid-template-columns: 280px minmax(0, 1fr) 340px;
    min-height: calc(100vh - 66px);
    font-size: 15px;
  }

  @media (max-width: 1000px) {
    .editor { grid-template-columns: 1fr; }
  }

  aside { padding: 16px; background: var(--surface); }
  .list { border-right: 1px solid var(--border); }
  .props { border-left: 1px solid var(--border); overflow-y: auto; max-height: calc(100vh - 66px); position: sticky; top: 66px; }
  .list ul { list-style: none; padding: 0; margin: 12px 0 0; display: grid; gap: 4px; }
  .list li button {
    width: 100%; text-align: left; padding: 8px 10px; border: 1px solid transparent; border-radius: 8px; background: none;
  }
  .list li button.on { border-color: var(--accent); background: var(--accent-soft); font-weight: 600; }

  .blank { display: grid; place-items: center; padding: 32px; }

  .stage { display: flex; flex-direction: column; min-width: 0; }

  .toolbar, .publish-bar {
    display: flex; flex-wrap: wrap; gap: 6px; align-items: center;
    padding: 10px 16px; background: var(--surface); border-bottom: 1px solid var(--border);
  }
  .publish-bar { border-bottom: 0; border-top: 1px solid var(--border); position: sticky; bottom: 0; }
  .spacer { flex: 1; }
  .toolbar button, .actions-row button, .secondary, .seg button {
    padding: 6px 10px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface);
  }
  button:disabled { opacity: 0.45; cursor: default; }
  .zoom { display: flex; align-items: center; gap: 4px; }
  .zoom input { width: 100px; }

  .canvas-wrap { flex: 1; overflow: auto; padding: 32px; text-align: center; }

  .canvas {
    position: relative;
    display: inline-block;
    background: #fff;
    box-shadow: 0 1px 6px rgb(0 0 0 / 0.25);
    touch-action: none;
    user-select: none;
    text-align: left;
  }
  .canvas img { position: absolute; inset: 0; width: 100%; height: 100%; image-rendering: auto; pointer-events: none; }

  .box { position: absolute; outline: 1px dashed rgb(11 110 79 / 0.35); cursor: move; }
  .box:hover { outline-color: rgb(11 110 79 / 0.8); }
  .box.selected { outline: 2px solid #0b6e4f; }
  .box.unknown { outline-color: #b3261e; }
  .canvas.dropping { outline: 2px dashed var(--accent); outline-offset: 4px; }
  .warn { color: #b3261e; font-size: 13px; margin: 0 0 10px; }

  .handle {
    position: absolute; width: 10px; height: 10px; margin: -5px 0 0 -5px;
    background: #fff; border: 2px solid #0b6e4f; border-radius: 2px;
  }
  .handle.nw { left: 0; top: 0; cursor: nwse-resize; }
  .handle.n { left: 50%; top: 0; cursor: ns-resize; }
  .handle.ne { left: 100%; top: 0; cursor: nesw-resize; }
  .handle.e { left: 100%; top: 50%; cursor: ew-resize; }
  .handle.se { left: 100%; top: 100%; cursor: nwse-resize; }
  .handle.s { left: 50%; top: 100%; cursor: ns-resize; }
  .handle.sw { left: 0; top: 100%; cursor: nesw-resize; }
  .handle.w { left: 0; top: 50%; cursor: ew-resize; }

  .dims { margin: 10px 0 0; font-size: 13px; }
  .hint { font-size: 13px; }

  .props h2 { font-size: 17px; margin: 0 0 12px; }
  .props h3 { font-size: 15px; margin: 20px 0 6px; }
  .props-head { display: flex; justify-content: space-between; align-items: baseline; }
  .props label { display: grid; gap: 3px; margin-bottom: 10px; font-size: 13px; font-weight: 600; }
  .props label.check { display: flex; gap: 6px; align-items: center; font-weight: 400; }
  .props label.pad { padding-top: 18px; }
  .props :global(input:not([type='checkbox']):not([type='range'])), .props textarea, .props select,
  .props :global(fieldset input), .props :global(fieldset select) {
    width: 100%; padding: 6px 8px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface);
    font: inherit; font-size: 14px; font-weight: 400; color: inherit;
  }
  .props textarea { resize: vertical; }
  .props :global(.mono) { font-family: ui-monospace, monospace; }
  .props :global(label) { font-size: 13px; }
  .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
  .grid4 { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; }
  .small { font-size: 13px; margin: -4px 0 10px; }

  .chips-head { font-size: 13px; font-weight: 600; margin-bottom: 4px; }
  .placeholders { display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 12px; }
  .ph {
    padding: 2px 8px; border: 1px solid var(--accent); border-radius: 999px; background: var(--accent-soft);
    font-size: 12px;
  }

  .seg { display: flex; gap: 4px; margin-bottom: 10px; }
  .seg button { min-width: 34px; }
  .seg button.on { border-color: var(--accent); background: var(--accent-soft); }

  .actions-row { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }

  .primary {
    padding: 8px 16px; border: 0; border-radius: 8px; background: var(--accent); color: var(--accent-text); font-weight: 700;
  }
  .danger-btn { padding: 6px 10px; border: 1px solid var(--danger); border-radius: 8px; background: none; color: var(--danger); }
  :global(.link) { border: 0; background: none; color: var(--accent); text-decoration: underline; padding: 0; }
  :global(.link.danger) { color: var(--danger); }
  .ok { color: var(--accent); font-weight: 600; }

  .props :global(.field) { margin-bottom: 10px; }
</style>

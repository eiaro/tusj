<script>
  import { getLabelTypes, getPlugins, getPrinters, previewLabel, printLabel } from './api.js'
  import { errorText, i18n, pick, registerPluginMessages, t } from './i18n.svelte.js'
  import Field from './Field.svelte'
  import LabelPreview from './LabelPreview.svelte'
  import Settings from './Settings.svelte'

  let labelTypes = $state(null)
  let printers = $state([])
  let printerId = $state(null)
  let choosingPrinter = $state(false)
  let copies = $state(1)
  const MAX_COPIES = 50
  let loadError = $state(null)
  let selectedId = $state(null)
  let showSettings = $state(false)
  let values = $state({})

  let previewUrl = $state('')
  let previewSize = $state(null)
  let previewError = $state(null)
  let printing = $state(false)
  let toast = $state(null)

  const labelType = $derived(selectedId ? labelTypes?.find((lt) => lt.id === selectedId) : null)
  // Printers whose loaded labels suit the label type.
  const compatible = $derived(labelType ? printers.filter((p) => fits(labelType.media, p.media_info)) : [])
  const printer = $derived(printers.find((p) => p.id === printerId))

  function fits(req, media) {
    return media.tape_mm >= req.min_width_mm && (media.endless ? req.endless : req.die_cut)
  }

  const missing = $derived(
    labelType ? labelType.fields.filter((f) => f.required && isEmpty(values[f.id])).map((f) => pick(f.label)) : [],
  )

  async function load() {
    loadError = null
    try {
      const [types, plugins, printerList] = await Promise.all([getLabelTypes(), getPlugins(), getPrinters()])
      for (const p of plugins) registerPluginMessages(p.id, p.messages)
      labelTypes = types
      printers = printerList
    } catch (e) {
      loadError = e
    }
  }
  load()

  function isEmpty(v) {
    return v == null || v === '' || (Array.isArray(v) && v.length === 0)
  }

  function initialValue(spec) {
    if (spec.type === 'multi-select') return spec.default ?? []
    if (spec.type === 'date' && spec.default === 'today') return new Date().toLocaleDateString('sv-SE')
    return spec.default ?? ''
  }

  function select(id) {
    selectedId = id
    values = Object.fromEntries(labelType.fields.map((f) => [f.id, initialValue(f)]))
    printerId = labelType.printer
    copies = 1
    choosingPrinter = false
    toast = null
  }

  function back() {
    // Plugins may have been enabled, disabled or reconfigured.
    if (showSettings) load()
    selectedId = null
    showSettings = false
    toast = null
  }

  // Refresh the preview shortly after the user stops typing (or switches language);
  // ignore out-of-order responses.
  let previewSeq = 0
  $effect(() => {
    const id = selectedId
    const fields = $state.snapshot(values)
    const lang = i18n.locale
    const printerChoice = printerId
    const ready = missing.length === 0
    const seq = ++previewSeq

    if (!id || !ready) {
      previewError = null
      return
    }
    const timer = setTimeout(async () => {
      try {
        const { blob, size } = await previewLabel(id, fields, lang, printerChoice)
        if (seq !== previewSeq) return
        if (previewUrl) URL.revokeObjectURL(previewUrl)
        previewUrl = URL.createObjectURL(blob)
        previewSize = size
        previewError = null
      } catch (e) {
        if (seq === previewSeq) previewError = e
      }
    }, 300)
    return () => clearTimeout(timer)
  })

  async function print() {
    printing = true
    toast = null
    try {
      const result = await printLabel(selectedId, $state.snapshot(values), i18n.locale, printerId, copies)
      toast = { ok: true, status: result.status, copies: result.copies }
    } catch (e) {
      toast = { ok: false, error: e }
    } finally {
      printing = false
    }
  }
</script>

<header>
  {#if labelType || showSettings}
    <button class="back" onclick={back} aria-label={t('common.back')}>‹</button>
    <h1>{showSettings ? t('common.settings') : pick(labelType.name)}</h1>
  {:else}
    <h1>Tusj</h1>
    <button class="settings" onclick={() => (showSettings = true)} aria-label={t('common.settings')}>⚙</button>
  {/if}
</header>

<main>
  {#if showSettings}
    <Settings />
  {:else if loadError}
    <p class="error">{t('home.loadError', { error: errorText(loadError) })}</p>
  {:else if !labelTypes}
    <p class="muted">{t('home.loading')}</p>
  {:else if !labelType}
    <p class="muted">{t('home.prompt')}</p>
    <div class="templates">
      {#each labelTypes as lt (lt.id)}
        <button class="template" disabled={!lt.media_ok} onclick={() => select(lt.id)}>
          <span class="icon" aria-hidden="true">{lt.icon}</span>
          <span>{pick(lt.name)}</span>
          {#if !lt.media_ok}<span class="hint">{t('home.wrongMedia')}</span>{/if}
        </button>
      {/each}
    </div>
  {:else}
    <form onsubmit={(e) => { e.preventDefault(); print() }}>
      {#each labelType.fields as spec (spec.id)}
        <Field {spec} labelTypeId={labelType.id} bind:value={values[spec.id]} />
      {/each}

      <section class="preview" aria-live="polite">
        {#if missing.length}
          <p class="muted">{t('form.fillIn', { fields: missing.join(', ') })}</p>
        {:else if previewError}
          <p class="error">{errorText(previewError)}</p>
        {:else if previewUrl}
          <LabelPreview src={previewUrl} size={previewSize} />
        {/if}
      </section>

      <div class="actions">
        {#if toast}
          <p class="toast" class:error={!toast.ok}>{toast.ok ? `✓ ${t(`form.status.${toast.status}`)}${toast.copies > 1 ? ` (${t('form.copiesDone', { n: toast.copies })})` : ''}` : errorText(toast.error)}</p>
        {/if}
        {#if choosingPrinter}
          <ul class="printer-choice" aria-label={t('form.choosePrinter')}>
            {#each compatible as p (p.id)}
              <li>
                <button type="button" class:on={p.id === printerId}
                        onclick={() => { printerId = p.id; choosingPrinter = false; toast = null }}>
                  <span>{p.driver === 'file' ? '🗂️' : '🖨️'} {p.name}</span>
                  <span class="muted">{p.media_info.tape_mm} mm</span>
                </button>
              </li>
            {/each}
          </ul>
        {/if}
        <div class="print-row">
          <div class="copies" role="group" aria-label={t('form.copies')}>
            <button type="button" aria-label={t('form.fewer')} disabled={copies <= 1} onclick={() => copies--}>−</button>
            <output aria-live="polite" aria-label={t('form.copiesDone', { n: copies })}>{copies}</output>
            <button type="button" aria-label={t('form.more')} disabled={copies >= MAX_COPIES} onclick={() => copies++}>+</button>
          </div>
          <button type="submit" class="print" disabled={printing || missing.length > 0 || !printer}>
            {printing ? t('form.printing') : printer ? t('form.printTo', { printer: printer.name }) : t('form.print')}
          </button>
          {#if compatible.length > 1}
            <button type="button" class="change" aria-expanded={choosingPrinter} onclick={() => (choosingPrinter = !choosingPrinter)}>
              {t('form.change')}
            </button>
          {/if}
        </div>
      </div>
    </form>
  {/if}
</main>

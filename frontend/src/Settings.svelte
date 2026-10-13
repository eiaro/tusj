<script>
  import { getHealth, getPlugins, getPrinterOptions, getPrinters, getPrinterStatus } from './api.js'
  import JobLog from './JobLog.svelte'
  import { LOCALES, errorText, i18n, setLocale, t } from './i18n.svelte.js'
  import PluginSettings from './PluginSettings.svelte'
  import PrinterEditor from './PrinterEditor.svelte'

  let printers = $state(null)
  let options = $state(null)
  let printersError = $state(null)
  // id of the printer being edited, "new" while adding one, or null
  let editing = $state(null)

  // {printer id: {ok, error}} once checked
  let online = $state({})
  let checking = $state(false)

  async function checkPrinters() {
    checking = true
    try {
      online = Object.fromEntries((await getPrinterStatus()).map((s) => [s.id, s]))
    } catch {
      online = {}
    } finally {
      checking = false
    }
  }
  checkPrinters()

  // Injected by Vite from package.json (vite.config.js).
  const appVersion = __APP_VERSION__
  let serverVersion = $state(null)
  getHealth()
    .then((h) => (serverVersion = h.version))
    .catch(() => {})

  let plugins = $state(null)
  let pluginsError = $state(null)

  Promise.all([getPrinters(), getPrinterOptions()])
    .then(([p, o]) => {
      printers = p
      options = o
    })
    .catch((e) => (printersError = e))

  getPlugins()
    .then((p) => (plugins = p))
    .catch((e) => (pluginsError = e))

  function summary(p) {
    const where = p.driver === 'file' ? t('printers.drivers.file') : `${p.model} · ${p.connection.replace(/^tcp:\/\//, '')}`
    return `${where} · ${p.media_info.tape_mm} mm`
  }

  function saved(printer) {
    const i = printers.findIndex((p) => p.id === printer.id)
    if (i >= 0) printers[i] = printer
    else printers.push(printer)
    editing = null
    checkPrinters()
  }

  function deleted(id) {
    printers = printers.filter((p) => p.id !== id)
    editing = null
    // Plugins that used it now default to the first printer.
    getPlugins().then((p) => (plugins = p)).catch(() => {})
  }
</script>

<section class="language">
  <span class="label" id="language-label">{t('settings.language')}</span>
  <div class="segmented" role="radiogroup" aria-labelledby="language-label">
    {#each Object.entries(LOCALES) as [code, messages]}
      <button
        type="button"
        role="radio"
        aria-checked={i18n.locale === code}
        class:on={i18n.locale === code}
        lang={code}
        onclick={() => setLocale(code)}
      >
        {messages._name}
      </button>
    {/each}
  </div>
</section>

<section class="printers">
  <h2>{t('printers.title')}</h2>
  {#if printersError}
    <p class="status error">{t('settings.loadError', { error: errorText(printersError) })}</p>
  {:else if !printers}
    <p class="muted">{t('common.loading')}</p>
  {:else}
    <ul class="printer-list">
      {#each printers as p, i (p.id)}
        <li>
          {#if editing === p.id}
            <PrinterEditor printer={p} {options} canDelete={printers.length > 1} onsaved={saved} ondeleted={deleted}
                           oncancel={() => (editing = null)} />
          {:else}
            <button type="button" class="printer" disabled={editing !== null} onclick={() => (editing = p.id)}>
              <span class="icon" aria-hidden="true">{p.driver === 'file' ? '🗂️' : '🖨️'}</span>
              <span
                class="dot"
                class:ok={online[p.id]?.ok}
                class:down={online[p.id] && !online[p.id].ok}
                title={online[p.id] ? (online[p.id].ok ? t('printers.online') : errorText(online[p.id].error)) : t('printers.checking')}
              ></span>
              <span class="text">
                <span class="name">{p.name}{#if i === 0}<span class="badge">{t('printers.default')}</span>{/if}</span>
                <span class="meta">{summary(p)}</span>
                {#if online[p.id] && !online[p.id].ok}<span class="offline">{errorText(online[p.id].error)}</span>{/if}
              </span>
              <span class="chevron" aria-hidden="true">›</span>
            </button>
          {/if}
        </li>
      {/each}
      {#if editing === 'new'}
        <li><PrinterEditor {options} onsaved={saved} oncancel={() => (editing = null)} /></li>
      {/if}
    </ul>
    {#if editing === null}
      <button type="button" class="add" onclick={() => (editing = 'new')}>+ {t('printers.add')}</button>
    {/if}
    {#if printers.length > 1}<p class="hint">{t('printers.defaultHint')}</p>{/if}
    <button type="button" class="recheck" disabled={checking} onclick={checkPrinters}>
      {checking ? t('printers.checking') : t('printers.recheck')}
    </button>
  {/if}
</section>

<section class="jobs">
  <h2>{t('jobs.title')}</h2>
  {#if printers}<JobLog {printers} />{/if}
</section>

<section class="plugins">
  <h2>{t('plugins.title')}</h2>
  {#if pluginsError}
    <p class="status error">{errorText(pluginsError)}</p>
  {:else if !plugins || !printers}
    <p class="muted">{t('common.loading')}</p>
  {:else}
    <!-- keyed on the printer too: deleting a printer resets plugins that used it -->
    {#each plugins as p (`${p.id}:${p.printer ?? ''}`)}
      <PluginSettings plugin={p} {printers} />
    {/each}
  {/if}
</section>

<footer class="about">
  Tusj {appVersion}
  {#if serverVersion && serverVersion !== appVersion}
    · {t('about.server', { version: serverVersion })}
  {/if}
</footer>

<style>
  .hint { margin: 8px 0 0; color: var(--muted); font-size: 14px; }
  .status.error { font-weight: 600; color: var(--danger); }

  .language { margin-bottom: 24px; }
  .language .label { display: block; margin-bottom: 6px; font-weight: 600; }

  .segmented {
    display: inline-flex;
    padding: 3px;
    border: 1px solid var(--border);
    border-radius: 999px;
    background: var(--surface);
  }

  .segmented button {
    min-height: 40px;
    padding: 6px 18px;
    border: 0;
    border-radius: 999px;
    background: none;
  }

  .segmented button.on { background: var(--accent); color: var(--accent-text); font-weight: 600; }

  h2 { margin: 0 0 10px; font-size: 17px; }

  .about { margin-top: 32px; text-align: center; color: var(--muted); font-size: 13px; }
  .printers, .plugins, .jobs { margin-top: 24px; padding-top: 20px; border-top: 1px solid var(--border); }

  .printer-list { list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; }

  .printer {
    display: flex;
    align-items: center;
    gap: 12px;
    width: 100%;
    padding: 12px 14px;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--surface);
    text-align: left;
  }

  .printer:disabled { opacity: 0.5; cursor: default; }
  .printer .icon { font-size: 24px; }
  .printer .text { display: flex; flex: 1; min-width: 0; flex-direction: column; }
  .printer .name { font-weight: 600; }
  .printer .meta { color: var(--muted); font-size: 14px; overflow-wrap: anywhere; }
  .printer .chevron { color: var(--muted); font-size: 24px; }
  .printer .offline { color: var(--danger); font-size: 13px; }

  .dot {
    flex: none;
    width: 10px;
    height: 10px;
    margin-left: -6px;
    border-radius: 50%;
    background: var(--border);
  }

  .dot.ok { background: var(--accent); }
  .dot.down { background: var(--danger); }

  .recheck {
    margin-top: 8px;
    padding: 4px 0;
    border: 0;
    background: none;
    color: var(--accent);
    text-decoration: underline;
    font-size: 14px;
  }

  .badge {
    margin-left: 8px;
    padding: 1px 8px;
    border-radius: 999px;
    background: var(--accent-soft);
    color: var(--accent);
    font-size: 12px;
    font-weight: 600;
  }

  .add {
    width: 100%;
    min-height: 48px;
    margin-top: 8px;
    border: 1px dashed var(--border);
    border-radius: var(--radius);
    background: none;
    color: var(--accent);
    font-weight: 600;
  }
</style>

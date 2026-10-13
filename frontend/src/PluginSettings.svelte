<script>
  // One plugin under Settings: enable/disable, its settings form (built from the plugin's
  // settings_schema) and an optional connection test.
  import { untrack } from 'svelte'
  import { checkPlugin, updatePlugin } from './api.js'
  import { errorText, pick, t } from './i18n.svelte.js'

  let { plugin: initial, printers = [] } = $props()

  // A local copy: it is replaced by the server's answer after every change.
  let plugin = $state(untrack(() => initial))
  let draft = $state(untrack(() => freshDraft(initial)))
  let busy = $state(false)
  let status = $state(null)

  // Secrets are never sent to the browser; their inputs start empty and stay empty unless
  // the user types a new value.
  function freshDraft(p) {
    return Object.fromEntries(
      p.settings_schema.map((s) => [s.id, s.type === 'secret' ? '' : (p.settings[s.id] ?? s.default ?? (s.type === 'boolean' ? false : ''))]),
    )
  }

  const dirty = $derived(
    plugin.settings_schema.some((s) =>
      s.type === 'secret' ? draft[s.id] !== '' : draft[s.id] !== (plugin.settings[s.id] ?? s.default ?? (s.type === 'boolean' ? false : '')),
    ),
  )

  async function run(action, okKey) {
    busy = true
    status = null
    try {
      await action()
      if (okKey) status = { ok: true, key: okKey }
    } catch (e) {
      status = { ok: false, error: e }
    } finally {
      busy = false
    }
  }

  const toggleEnabled = () =>
    run(async () => {
      plugin = await updatePlugin(plugin.id, { enabled: !plugin.enabled })
    })

  const save = () =>
    run(async () => {
      plugin = await updatePlugin(plugin.id, { settings: $state.snapshot(draft) })
      draft = freshDraft(plugin)
    }, 'settings.saved')

  const check = () => run(() => checkPlugin(plugin.id), 'plugins.checkOk')

  const setPrinter = (e) =>
    run(async () => {
      plugin = await updatePlugin(plugin.id, { printer: e.currentTarget.value || null })
    }, 'settings.saved')
</script>

<article class="plugin" class:disabled={!plugin.enabled}>
  <header>
    <div>
      <h3>{pick(plugin.name)}</h3>
      <p class="meta">
        {#if plugin.version}v{plugin.version}{/if}
        {#if plugin.builtin} · {t('plugins.builtin')}{/if}
      </p>
    </div>
    {#if !plugin.error || plugin.settings_schema.length}
      <label class="switch">
        <input type="checkbox" checked={plugin.enabled} disabled={busy} onchange={toggleEnabled} />
        <span>{plugin.enabled ? t('plugins.enabled') : t('plugins.disabled')}</span>
      </label>
    {/if}
  </header>

  {#if plugin.description}<p class="description">{pick(plugin.description)}</p>{/if}

  {#if plugin.enabled && !plugin.error && printers.length > 1}
    <div class="field">
      <label for="plugin-{plugin.id}-printer">{t('plugins.printer')}</label>
      <select id="plugin-{plugin.id}-printer" value={plugin.printer ?? ''} disabled={busy} onchange={setPrinter}>
        <option value="">{t('plugins.firstPrinter', { name: printers[0].name })}</option>
        {#each printers as p (p.id)}<option value={p.id}>{p.name}</option>{/each}
      </select>
    </div>
  {/if}

  {#if plugin.error}
    <p class="status error">{t('plugins.failed')}: <code>{plugin.error}</code></p>
  {/if}

  {#if plugin.enabled && plugin.settings_schema.length}
    <form onsubmit={(e) => { e.preventDefault(); save() }}>
      {#each plugin.settings_schema as s (s.id)}
        {@const inputId = `plugin-${plugin.id}-${s.id}`}
        <div class="field">
          {#if s.type === 'boolean'}
            <label class="check"><input type="checkbox" bind:checked={draft[s.id]} /> {pick(s.label)}</label>
          {:else}
            <label for={inputId}>{pick(s.label)}{#if s.required}<span class="req">*</span>{/if}</label>
            <input
              id={inputId}
              type={s.type === 'secret' ? 'password' : s.type === 'url' ? 'url' : 'text'}
              autocomplete={s.type === 'secret' ? 'new-password' : 'off'}
              autocapitalize="off"
              spellcheck="false"
              placeholder={s.type === 'secret' && plugin.settings[s.id] ? t('plugins.secretSet') : ''}
              bind:value={draft[s.id]}
            />
          {/if}
          {#if s.help}<p class="hint">{pick(s.help)}</p>{/if}
        </div>
      {/each}

      <div class="buttons">
        {#if plugin.checkable}
          <button type="button" class="secondary" disabled={busy || dirty} onclick={check}>{t('plugins.check')}</button>
        {/if}
        <button type="submit" class="primary" disabled={busy || !dirty}>{t('settings.save')}</button>
      </div>
    </form>
  {:else if plugin.enabled && plugin.checkable}
    <div class="buttons">
      <button type="button" class="secondary" disabled={busy} onclick={check}>{t('plugins.check')}</button>
    </div>
  {/if}

  {#if status}
    <p class="status" class:error={!status.ok}>{status.ok ? `✓ ${t(status.key)}` : errorText(status.error)}</p>
  {/if}
</article>

<style>
  .plugin {
    margin-bottom: 12px;
    padding: 14px;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--surface);
  }

  .plugin.disabled h3 { color: var(--muted); }

  header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
  h3 { margin: 0; font-size: 16px; }
  .meta { margin: 2px 0 0; color: var(--muted); font-size: 13px; }
  .description { margin: 8px 0 12px; color: var(--muted); font-size: 14px; }

  .switch { display: flex; align-items: center; gap: 6px; font-size: 14px; white-space: nowrap; }
  .switch input, .check input { width: 20px; height: 20px; accent-color: var(--accent); }
  .check { display: flex; align-items: center; gap: 8px; }

  .hint { margin: 6px 0 0; color: var(--muted); font-size: 14px; }
  code { font-size: 13px; word-break: break-word; }

  .status { font-weight: 600; color: var(--accent); margin: 10px 0 0; }
  .status.error { color: var(--danger); }

  .buttons { display: grid; grid-auto-flow: column; grid-auto-columns: 1fr; gap: 12px; }

  .buttons button {
    min-height: 48px;
    border-radius: var(--radius);
    font-weight: 700;
  }

  .primary { border: 0; background: var(--accent); color: var(--accent-text); }
  .secondary { border: 1px solid var(--border); background: var(--bg); }
  .buttons button:disabled { opacity: 0.45; cursor: default; }
</style>

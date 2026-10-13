<script>
  // Add or edit one printer. For Brother printers on the network it can search the subnet
  // and fill in the address (and the model, when the printer reports it).
  import { untrack } from 'svelte'
  import { addPrinter, deletePrinter, getDefaultSubnet, scanPrinters, testPrinter, updatePrinter } from './api.js'
  import { errorText, t } from './i18n.svelte.js'

  let { printer = null, options, canDelete = false, onsaved, ondeleted, oncancel } = $props()

  const CONNECTIONS = { network: 'tcp://', usb: 'usb://', device: 'file://' }

  function parse(connection = '') {
    for (const [kind, prefix] of Object.entries(CONNECTIONS)) {
      if (connection.startsWith(prefix)) return { kind, value: kind === 'network' ? connection.slice(prefix.length) : connection }
    }
    return { kind: 'network', value: '' }
  }

  const initial = untrack(() => printer)
  const conn = parse(initial?.connection)
  let name = $state(initial?.name ?? '')
  let driver = $state(initial?.driver ?? 'brother_ql')
  let connKind = $state(conn.kind)
  let connValue = $state(conn.value)
  let model = $state(initial?.model ?? 'QL-820NWB')
  let media = $state(initial?.media ?? '62')

  let busy = $state(false)
  let status = $state(null)

  const mediaChoices = $derived(options.media.filter((m) => m.supported || m.id === media))

  function mediaLabel(m) {
    const kind = m.endless ? t('printers.mediaEndless') : t('printers.mediaDieCut', { length: m.length_mm })
    return `${m.tape_mm} mm ${kind}${m.two_color ? ` · ${t('printers.mediaTwoColor')}` : ''}`
  }

  function payload() {
    const out = { name: name.trim(), driver, media }
    if (driver === 'brother_ql') {
      out.model = model
      const v = connValue.trim()
      out.connection = connKind === 'network' ? `tcp://${v}` : v
    }
    return out
  }

  async function run(action, okKey) {
    busy = true
    status = null
    try {
      const result = await action()
      if (okKey) status = { ok: true, key: okKey }
      return result
    } catch (e) {
      status = { ok: false, error: e }
    } finally {
      busy = false
    }
  }

  const test = () => run(() => testPrinter(payload()), 'printers.testOk')

  async function save() {
    const saved = await run(() => (initial ? updatePrinter(initial.id, payload()) : addPrinter(payload())))
    if (saved) onsaved?.(saved)
  }

  async function remove() {
    if (!confirm(t('printers.confirmDelete', { name: initial.name }))) return
    const ok = await run(() => deletePrinter(initial.id))
    if (ok) ondeleted?.(initial.id)
  }

  // --- Network search ---
  let subnet = $state('')
  let scanning = $state(false)
  let scanResult = $state(null)
  let scanError = $state(null)
  let showScan = $state(false)

  function openScan() {
    showScan = !showScan
    if (showScan && !subnet) getDefaultSubnet().then((d) => (subnet ||= d.subnet)).catch(() => {})
  }

  async function scan() {
    scanning = true
    scanError = null
    scanResult = null
    try {
      scanResult = (await scanPrinters(subnet.trim())).printers
    } catch (e) {
      scanError = e
    } finally {
      scanning = false
    }
  }

  function choose(found) {
    connKind = 'network'
    connValue = found.ip
    // "Brother QL-820NWB" → QL-820NWB, if it's a model we know
    const known = options.models.find((m) => found.model?.includes(m))
    if (known) model = known
    if (!name.trim()) name = found.name || found.model || found.ip
    status = null
  }
</script>

<form class="editor" onsubmit={(e) => { e.preventDefault(); save() }}>
  <div class="field">
    <label for="printer-name">{t('printers.name')}<span class="req">*</span></label>
    <input id="printer-name" type="text" autocomplete="off" placeholder={t('printers.namePlaceholder')} bind:value={name} />
  </div>

  <div class="field">
    <span class="label">{t('printers.driver')}</span>
    <div class="chips">
      <button type="button" class="chip" class:on={driver === 'brother_ql'} onclick={() => (driver = 'brother_ql')}>
        {t('printers.drivers.brother_ql')}
      </button>
      <button type="button" class="chip" class:on={driver === 'file'} onclick={() => (driver = 'file')}>
        {t('printers.drivers.file')}
      </button>
    </div>
    {#if driver === 'file'}<p class="hint">{t('printers.fileHint')}</p>{/if}
  </div>

  {#if driver === 'brother_ql'}
    <div class="field">
      <span class="label">{t('printers.connection')}</span>
      <div class="chips">
        {#each Object.keys(CONNECTIONS) as kind}
          <button type="button" class="chip" class:on={connKind === kind}
                  onclick={() => { if (connKind !== kind) { connKind = kind; connValue = '' } }}>
            {t(`printers.connections.${kind}`)}
          </button>
        {/each}
      </div>
      <input
        type="text"
        aria-label={t(`printers.connections.${connKind}`)}
        inputmode={connKind === 'network' ? 'decimal' : 'text'}
        autocomplete="off"
        autocapitalize="off"
        spellcheck="false"
        placeholder={{ network: '192.168.1.100', usb: 'usb://0x04f9:0x209d', device: 'file:///dev/usb/lp0' }[connKind]}
        bind:value={connValue}
        oninput={() => (status = null)}
      />
      <p class="hint">{t(`printers.connectionHints.${connKind}`)}</p>

      {#if connKind === 'network'}
        <button type="button" class="link" onclick={openScan}>{t('settings.scanTitle')}</button>
        {#if showScan}
          <div class="scan">
            <div class="scan-form">
              <input type="text" aria-label={t('settings.subnet')} placeholder="192.168.1.0/24" autocomplete="off"
                     autocapitalize="off" spellcheck="false" bind:value={subnet}
                     onkeydown={(e) => { if (e.key === 'Enter') { e.preventDefault(); scan() } }} />
              <button type="button" class="secondary" disabled={scanning || !subnet.trim()} onclick={scan}>
                {scanning ? t('settings.scanning') : t('settings.scan')}
              </button>
            </div>
            {#if scanError}
              <p class="status error">{errorText(scanError)}</p>
            {:else if scanResult && scanResult.length === 0}
              <p class="hint">{t('settings.noneFound', { subnet })}</p>
            {:else if scanResult}
              <ul class="found">
                {#each scanResult as p (p.ip)}
                  <li>
                    <button type="button" class:current={p.ip === connValue.trim()} onclick={() => choose(p)}>
                      <span class="model">{p.model ?? t('settings.unknownPrinter')}</span>
                      <span class="addr">{p.ip}{p.name ? ` · ${p.name}` : ''}</span>
                    </button>
                  </li>
                {/each}
              </ul>
            {/if}
          </div>
        {/if}
      {/if}
    </div>

    <div class="field">
      <label for="printer-model">{t('printers.model')}</label>
      <select id="printer-model" bind:value={model}>
        {#each options.models as m}<option value={m}>{m}</option>{/each}
      </select>
    </div>
  {/if}

  <div class="field">
    <label for="printer-media">{t('printers.media')}</label>
    <select id="printer-media" bind:value={media}>
      {#each mediaChoices as m (m.id)}<option value={m.id}>{mediaLabel(m)}</option>{/each}
    </select>
  </div>

  {#if status}
    <p class="status" class:error={!status.ok}>{status.ok ? `✓ ${t(status.key)}` : errorText(status.error)}</p>
  {/if}

  <div class="buttons">
    <button type="button" class="secondary" disabled={busy || !name.trim()} onclick={test}>{t('settings.test')}</button>
    <button type="submit" class="primary" disabled={busy || !name.trim()}>{t('settings.save')}</button>
  </div>
  <div class="secondary-actions">
    <button type="button" class="link" onclick={() => oncancel?.()}>{t('common.cancel')}</button>
    {#if initial && canDelete}
      <button type="button" class="link danger" disabled={busy} onclick={remove}>{t('printers.delete')}</button>
    {/if}
  </div>
</form>

<style>
  .editor {
    padding: 14px;
    border: 1px solid var(--accent);
    border-radius: var(--radius);
    background: var(--surface);
  }

  .hint { margin: 6px 0 0; color: var(--muted); font-size: 14px; }
  .chips { margin-bottom: 8px; }

  .link {
    margin-top: 8px;
    padding: 4px 0;
    border: 0;
    background: none;
    color: var(--accent);
    text-decoration: underline;
    font-size: 15px;
  }

  .link.danger { color: var(--danger); }

  .scan { margin-top: 8px; }
  .scan-form { display: flex; gap: 8px; }
  .scan-form input { flex: 1; min-width: 0; }
  .scan-form button { min-width: 90px; border-radius: var(--radius); font-weight: 700; }

  .found { list-style: none; margin: 10px 0 0; padding: 0; display: grid; gap: 8px; }

  .found button {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    width: 100%;
    padding: 10px 12px;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--bg);
    text-align: left;
  }

  .found button.current { border-color: var(--accent); background: var(--accent-soft); }
  .found .model { font-weight: 600; }
  .found .addr { color: var(--muted); font-size: 14px; }

  .status { font-weight: 600; color: var(--accent); margin: 0 0 12px; }
  .status.error { color: var(--danger); }

  .buttons { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }

  .buttons button {
    min-height: 48px;
    border-radius: var(--radius);
    font-weight: 700;
  }

  .primary { border: 0; background: var(--accent); color: var(--accent-text); }
  .secondary { border: 1px solid var(--border); background: var(--bg); }
  button:disabled { opacity: 0.45; cursor: default; }

  .secondary-actions { display: flex; justify-content: space-between; margin-top: 4px; }
</style>

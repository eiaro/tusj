<script>
  // The last print jobs (kept by the backend until it restarts), with "print again".
  import { getJobs, reprintJob } from './api.js'
  import { errorText, i18n, pick, t } from './i18n.svelte.js'

  let { printers = [] } = $props()

  let jobs = $state(null)
  let loadError = $state(null)
  let busy = $state(null)
  // id of the job a status message belongs to
  let status = $state(null)
  let showAll = $state(false)

  const SHOWN = 8
  const visible = $derived(showAll ? jobs : jobs?.slice(0, SHOWN))

  async function load() {
    try {
      jobs = await getJobs()
    } catch (e) {
      loadError = e
    }
  }
  load()

  function printerName(id) {
    return printers.find((p) => p.id === id)?.name ?? id
  }

  function when(iso) {
    const d = new Date(iso)
    const sameDay = d.toDateString() === new Date().toDateString()
    const opts = sameDay ? { hour: '2-digit', minute: '2-digit' } : { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }
    return d.toLocaleString(i18n.locale, opts)
  }

  async function again(job) {
    busy = job.id
    status = null
    try {
      const result = await reprintJob(job.id)
      status = { job: job.id, ok: true, status: result.status }
      await load()
    } catch (e) {
      status = { job: job.id, ok: false, error: e }
      await load()
    } finally {
      busy = null
    }
  }
</script>

{#if loadError}
  <p class="error">{errorText(loadError)}</p>
{:else if !jobs}
  <p class="muted">{t('common.loading')}</p>
{:else if !jobs.length}
  <p class="muted">{t('jobs.empty')}</p>
{:else}
  <ul class="jobs">
    {#each visible as job (job.id)}
      <li class:failed={job.error}>
        <div class="what">
          <span class="name">{pick(job.label_name)}{#if job.copies > 1}<span class="count"> ×{job.copies}</span>{/if}</span>
          <span class="meta">
            {when(job.time)} · {printerName(job.printer)} ·
            {#if job.error}
              <span class="error">{errorText(job.error)}</span>
            {:else}
              {t(`form.status.${job.status}`)}
            {/if}
          </span>
        </div>
        <button type="button" disabled={busy !== null} onclick={() => again(job)}>
          {busy === job.id ? t('form.printing') : t('jobs.again')}
        </button>
      </li>
      {#if status?.job === job.id}
        <li class="result" class:error={!status.ok}>
          {status.ok ? `✓ ${t(`form.status.${status.status}`)}` : errorText(status.error)}
        </li>
      {/if}
    {/each}
  </ul>
  {#if jobs.length > SHOWN && !showAll}
    <button type="button" class="more" onclick={() => (showAll = true)}>{t('jobs.showAll', { n: jobs.length })}</button>
  {/if}
  <p class="hint">{t('jobs.hint')}</p>
{/if}

<style>
  .jobs { list-style: none; margin: 0; padding: 0; display: grid; gap: 6px; }

  .jobs li {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 12px;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--surface);
  }

  .jobs li.failed { border-color: var(--danger); }
  .jobs li.result { border: 0; background: none; padding: 0 12px 4px; font-weight: 600; color: var(--accent); }
  .jobs li.result.error { color: var(--danger); }

  .what { display: flex; flex: 1; min-width: 0; flex-direction: column; }
  .name { font-weight: 600; }
  .count { color: var(--muted); font-weight: 400; }
  .meta { color: var(--muted); font-size: 13px; overflow-wrap: anywhere; }
  .meta .error { color: var(--danger); }

  .jobs button {
    flex: none;
    min-height: 40px;
    padding: 0 12px;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--bg);
    font-size: 14px;
    font-weight: 600;
  }

  .jobs button:disabled { opacity: 0.5; cursor: default; }

  .more {
    margin-top: 8px;
    padding: 4px 0;
    border: 0;
    background: none;
    color: var(--accent);
    text-decoration: underline;
  }

  .hint { margin: 8px 0 0; color: var(--muted); font-size: 13px; }
</style>

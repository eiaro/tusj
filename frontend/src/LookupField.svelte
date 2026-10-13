<script>
  // Search-as-you-type field: options come from the plugin's search(); the field's value is
  // the chosen option's value, while its label is shown in the input.
  import { searchLookup } from './api.js'
  import { errorText, i18n, pick, t } from './i18n.svelte.js'

  let { id, spec, labelTypeId, value = $bindable() } = $props()

  let query = $state('')
  let chosen = $state(null)
  let results = $state([])
  let open = $state(false)
  let loading = $state(false)
  let error = $state(null)
  let active = $state(-1)

  let seq = 0
  let timer
  function onInput() {
    chosen = null
    value = ''
    open = true
    active = -1
    clearTimeout(timer)
    const q = query.trim()
    if (!q) {
      results = []
      loading = false
      return
    }
    // Show "Searching…" during the debounce too, not a premature "No matches".
    loading = true
    error = null
    results = []
    timer = setTimeout(() => search(q), 250)
  }

  async function search(q) {
    const mine = ++seq
    loading = true
    error = null
    try {
      const found = await searchLookup(labelTypeId, spec.id, q, i18n.locale)
      if (mine === seq) results = found
    } catch (e) {
      if (mine === seq) error = e
    } finally {
      if (mine === seq) loading = false
    }
  }

  function choose(opt) {
    chosen = opt
    value = opt.value
    query = pick(opt.label)
    open = false
  }

  function clear() {
    chosen = null
    value = ''
    query = ''
    results = []
  }

  function onKeydown(e) {
    if (!open || !results.length) return
    if (e.key === 'ArrowDown') active = (active + 1) % results.length
    else if (e.key === 'ArrowUp') active = (active - 1 + results.length) % results.length
    else if (e.key === 'Enter' && active >= 0) choose(results[active])
    else if (e.key === 'Escape') open = false
    else return
    e.preventDefault()
  }
</script>

<div class="lookup">
  <div class="lookup-input">
    <input
      {id}
      type="search"
      role="combobox"
      aria-expanded={open && results.length > 0}
      aria-controls="{id}-results"
      aria-autocomplete="list"
      autocomplete="off"
      placeholder={spec.placeholder ? pick(spec.placeholder) : t('form.search')}
      bind:value={query}
      oninput={onInput}
      onkeydown={onKeydown}
      onfocus={() => (open = !chosen && results.length > 0)}
      onblur={() => setTimeout(() => (open = false), 150)}
    />
    {#if chosen}
      <button type="button" class="lookup-clear" aria-label={t('form.clear')} onclick={clear}>×</button>
    {/if}
  </div>

  {#if chosen?.description}
    <p class="lookup-chosen">{pick(chosen.description)}</p>
  {/if}

  {#if open && query.trim()}
    <ul class="lookup-results" id="{id}-results" role="listbox">
      {#if loading}
        <li class="muted">{t('form.searching')}</li>
      {:else if error}
        <li class="error">{errorText(error)}</li>
      {:else if !results.length}
        <li class="muted">{t('form.noResults')}</li>
      {:else}
        {#each results as opt, i (opt.value)}
          <li role="option" aria-selected={i === active}>
            <button type="button" class:active={i === active} onmousedown={(e) => e.preventDefault()} onclick={() => choose(opt)}>
              <span>{opt.icon ? `${opt.icon} ` : ''}{pick(opt.label)}</span>
              {#if opt.description}<span class="muted small">{pick(opt.description)}</span>{/if}
            </button>
          </li>
        {/each}
      {/if}
    </ul>
  {/if}
</div>

<style>
  .lookup { position: relative; }
  .lookup-input { position: relative; }
  .lookup-input input { padding-right: 44px; }

  .lookup-clear {
    position: absolute;
    top: 50%;
    right: 4px;
    width: 40px;
    height: 40px;
    transform: translateY(-50%);
    border: 0;
    background: none;
    font-size: 22px;
    color: var(--muted);
  }

  .lookup-chosen { margin: 6px 0 0; color: var(--muted); font-size: 14px; }

  .lookup-results {
    position: absolute;
    z-index: 2;
    left: 0;
    right: 0;
    max-height: 280px;
    overflow-y: auto;
    margin: 4px 0 0;
    padding: 4px;
    list-style: none;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    box-shadow: 0 6px 20px rgb(0 0 0 / 0.15);
  }

  .lookup-results li.muted, .lookup-results li.error { padding: 10px 12px; }

  .lookup-results button {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    width: 100%;
    min-height: 44px;
    padding: 8px 12px;
    border: 0;
    border-radius: 8px;
    background: none;
    text-align: left;
  }

  .lookup-results button:hover, .lookup-results button.active { background: var(--accent-soft); }
  .small { font-size: 13px; }
</style>

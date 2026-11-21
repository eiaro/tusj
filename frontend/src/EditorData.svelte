<script>
  // The data a design can show: where it comes from (a data source such as an InvenTree part,
  // fields typed in when printing, today's date), with what each one holds right now. Items are
  // dragged onto the label, or clicked to put them in the selected element.
  import { pick, t } from './i18n.svelte.js'
  import LookupField from './LookupField.svelte'

  let {
    design,            // the design being edited
    sources = [],      // data sources from /designs/meta
    source = null,     // the chosen one
    testValues = $bindable(),
    values = {},       // placeholder -> current text, from /designs/values
    search,            // (query, lang) => options, for the chosen source
    onuse,             // (key) => void: put {key} on the label
    onsource,          // (source id or null) => void
  } = $props()

  const fieldItems = $derived(design.fields.map((f) => ({ key: f.id, label: pick(f.label) || f.id, field: f })))
  const sourceItems = $derived(
    (source?.variables ?? []).map((v) => ({ key: `${source.key}.${v.id}`, label: pick(v.label) })),
  )

  function changeSource(id) {
    onsource(id || null)
    testValues = {}
  }

  function dragStart(e, key) {
    e.dataTransfer.setData('application/x-tusj-placeholder', key)
    e.dataTransfer.setData('text/plain', `{${key}}`)
    e.dataTransfer.effectAllowed = 'copy'
  }

  const typedField = (f) => f.type === 'text' || f.type === 'number'
</script>

{#snippet item(it)}
  <button type="button" class="item" draggable="true" title={`{${it.key}}`}
          ondragstart={(e) => dragStart(e, it.key)} onclick={() => onuse(it.key)}>
    <span class="grip" aria-hidden="true">⠿</span>
    <span class="name">{it.label}</span>
    <span class="value">{values[it.key] || '—'}</span>
  </button>
{/snippet}

<section class="data">
  <h2>{t('editor.data.heading')}</h2>
  <p class="muted small">{t('editor.data.hint')}</p>

  <label class="from">{t('editor.design.source')}
    <select value={design.source ?? ''} onchange={(e) => changeSource(e.currentTarget.value)}>
      <option value="">{t('editor.design.noSource')}</option>
      {#each sources as s (s.id)}<option value={s.id}>{s.icon} {pick(s.name)}</option>{/each}
    </select>
  </label>

  {#if source}
    <div class="group">
      <div class="lookup">
        <span class="label">{t('editor.data.showWith')}</span>
        {#key source.id}
          <LookupField id="data-source-lookup" spec={{ id: source.key, label: source.name, type: 'lookup' }}
                       searchFn={search} bind:value={testValues[source.key]} />
        {/key}
        <span class="muted small">{testValues[source.key] ? t('editor.data.showingReal') : t('editor.data.showingSample', { name: pick(source.name) })}</span>
      </div>
      {#each sourceItems as it (it.key)}{@render item(it)}{/each}
    </div>
  {/if}

  <h3>{t('editor.data.fields')}</h3>
  {#if fieldItems.length}
    <div class="group">
      {#each fieldItems as it (it.key)}
        {@render item(it)}
        {#if typedField(it.field)}
          <input class="try" placeholder={t('editor.data.tryValue')} aria-label={`${it.label}: ${t('editor.data.tryValue')}`}
                 bind:value={testValues[it.key]} />
        {/if}
      {/each}
    </div>
  {:else}
    <p class="muted small">{t('editor.data.noFields')}</p>
  {/if}

  <h3>{t('editor.data.other')}</h3>
  <div class="group">
    {@render item({ key: 'today', label: t('editor.placeholders.today') })}
  </div>
</section>

<style>
  .data { margin-top: 20px; padding-top: 16px; border-top: 1px solid var(--border); }
  h2 { font-size: 17px; margin: 0 0 4px; }
  h3 { font-size: 13px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted); margin: 16px 0 6px; }
  .small { font-size: 13px; margin: 0 0 10px; }
  .from { display: grid; gap: 4px; font-size: 14px; margin-bottom: 10px; }
  .group { display: grid; gap: 4px; }
  .lookup { display: grid; gap: 4px; margin-bottom: 8px; padding: 8px; border-radius: 8px; background: var(--accent-soft); }
  .lookup .label { font-size: 14px; font-weight: 600; }

  .item {
    display: grid; grid-template-columns: auto minmax(0, 1fr); column-gap: 6px;
    text-align: left; padding: 6px 8px; border: 1px solid var(--border); border-radius: 8px;
    background: var(--bg, #fff); cursor: grab; font-size: 14px;
  }
  .item:hover { border-color: var(--accent); }
  .item:active { cursor: grabbing; }
  .grip { grid-row: span 2; color: var(--muted); align-self: center; }
  .name { font-weight: 600; }
  .value { color: var(--muted); font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .try { font-size: 13px; padding: 4px 8px; margin: -2px 0 4px 18px; width: calc(100% - 18px); box-sizing: border-box; }
</style>

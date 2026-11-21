<script>
  // The fields a design asks for when printing: id, label per language, type and type options.
  import { LOCALES, t } from './i18n.svelte.js'

  let { fields = $bindable(), types } = $props()

  const languages = Object.keys(LOCALES)

  function add() {
    let n = fields.length + 1
    while (fields.some((f) => f.id === `field${n}`)) n++
    fields.push({ id: `field${n}`, type: 'text', label: Object.fromEntries(languages.map((l) => [l, ''])), required: false })
  }

  function setType(f, type) {
    f.type = type
    delete f.presets
    delete f.options
    delete f.default
    if (type === 'date-presets') f.presets = ['+3d', '+1w', '+1m']
    if (type === 'date') f.default = 'today'
    if (type === 'select') f.options = [{ value: 'a', label: 'A' }]
  }

  const slug = (s) => s.toLowerCase().normalize('NFKD').replace(/[^\w]+/g, '-').replace(/^-|-$/g, '') || 'x'

  function optionsText(f) {
    return (f.options ?? []).map((o) => (typeof o.label === 'object' ? Object.values(o.label)[0] : o.label)).join(', ')
  }

  function setOptions(f, text) {
    f.options = text.split(',').map((s) => s.trim()).filter(Boolean).map((label) => ({ value: slug(label), label }))
  }
</script>

<div class="fields">
  {#each fields as f, i (i)}
    <fieldset>
      <div class="row">
        <label>{t('editor.fields.id')}
          <input class="mono" bind:value={f.id} spellcheck="false" />
        </label>
        <label>{t('editor.fields.type')}
          <select value={f.type} onchange={(e) => setType(f, e.currentTarget.value)}>
            {#each types as type}<option value={type}>{t(`editor.fields.types.${type}`)}</option>{/each}
          </select>
        </label>
      </div>
      {#each languages as lang}
        <label>{t('editor.fields.label')} ({lang})
          <input bind:value={f.label[lang]} />
        </label>
      {/each}
      {#if f.type === 'date-presets'}
        <label>{t('editor.fields.presets')}
          <input value={(f.presets ?? []).join(', ')} placeholder="+3d, +1w, +1m, +1y"
                 onchange={(e) => (f.presets = e.currentTarget.value.split(',').map((s) => s.trim()).filter(Boolean))} />
        </label>
      {:else if f.type === 'select'}
        <label>{t('editor.fields.options')}
          <input value={optionsText(f)} placeholder={t('editor.fields.optionsHint')}
                 onchange={(e) => setOptions(f, e.currentTarget.value)} />
        </label>
      {/if}
      <div class="row end">
        <label class="check"><input type="checkbox" bind:checked={f.required} /> {t('editor.fields.required')}</label>
        <button type="button" class="link danger" onclick={() => fields.splice(i, 1)}>{t('editor.fields.remove')}</button>
      </div>
    </fieldset>
  {/each}
  <button type="button" class="secondary" onclick={add}>+ {t('editor.fields.add')}</button>
</div>

<style>
  fieldset {
    margin: 0 0 10px;
    padding: 10px;
    border: 1px solid var(--border);
    border-radius: 8px;
    display: grid;
    gap: 6px;
  }
  .row { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
  .row.end { display: flex; justify-content: space-between; align-items: center; }
</style>

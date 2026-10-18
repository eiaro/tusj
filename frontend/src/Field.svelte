<script>
  import { pick, presetLabel, t } from './i18n.svelte.js'
  import LookupField from './LookupField.svelte'

  let { spec, labelTypeId, value = $bindable() } = $props()

  const id = $derived(`field-${spec.id}`)
  const label = $derived(pick(spec.label))
  const presets = $derived(spec.presets ?? [])
  const options = $derived(spec.options ?? [])
  // Few options without icons read best as chips; many as a dropdown.
  const selectAsChips = $derived(options.length <= 6)

  // date-presets: a preset value like "+1w", an ISO date (custom), or '' (none).
  let customDate = $state(false)
  const isCustom = $derived(customDate || (value && !presets.includes(value)))

  function pickPreset(v) {
    customDate = false
    value = v
  }

  function pickCustom() {
    customDate = true
    value = new Date().toLocaleDateString('sv-SE')
  }

  function toggle(optionValue) {
    value = value.includes(optionValue) ? value.filter((v) => v !== optionValue) : [...value, optionValue]
  }
</script>

{#snippet title(forId)}
  {#if forId}
    <label for={forId}>{label}{#if spec.required}<span class="req">*</span>{/if}</label>
  {:else}
    <span class="label">{label}{#if spec.required}<span class="req">*</span>{/if}</span>
  {/if}
{/snippet}

<div class="field">
  {#if spec.type === 'text'}
    {@render title(id)}
    <input {id} type="text" bind:value autocomplete="off" enterkeyhint="done"
      placeholder={spec.placeholder ? pick(spec.placeholder) : undefined} />
    {#if spec.help}<p class="hint">{pick(spec.help)}</p>{/if}
  {:else if spec.type === 'number'}
    {@render title(id)}
    <input {id} type="number" inputmode="decimal" min={spec.min} max={spec.max} step={spec.step ?? 'any'} bind:value />
  {:else if spec.type === 'date'}
    {@render title(id)}
    <input {id} type="date" bind:value />
  {:else if spec.type === 'date-presets'}
    {@render title()}
    <div class="chips">
      {#if !spec.required}
        <button type="button" class="chip" class:on={!value && !isCustom} onclick={() => pickPreset('')}>
          {t('form.none')}
        </button>
      {/if}
      {#each presets as preset}
        <button type="button" class="chip" class:on={value === preset && !isCustom} onclick={() => pickPreset(preset)}>
          {presetLabel(preset)}
        </button>
      {/each}
      <button type="button" class="chip" class:on={isCustom} onclick={pickCustom}>{t('form.customDate')}</button>
    </div>
    {#if isCustom}
      <input type="date" aria-label={t('form.customDateAria', { field: label })} bind:value />
    {/if}
  {:else if spec.type === 'select'}
    {#if selectAsChips}
      {@render title()}
      <div class="chips">
        {#if !spec.required}
          <button type="button" class="chip" class:on={!value} onclick={() => (value = '')}>{t('form.none')}</button>
        {/if}
        {#each options as opt (opt.value)}
          <button type="button" class="chip" class:on={value === opt.value} onclick={() => (value = opt.value)}>
            {#if opt.icon}<span aria-hidden="true">{opt.icon}</span>{/if}
            {pick(opt.label)}
          </button>
        {/each}
      </div>
    {:else}
      {@render title(id)}
      <select {id} bind:value>
        {#if !spec.required}<option value="">{t('form.none')}</option>{/if}
        {#each options as opt (opt.value)}
          <option value={opt.value}>{opt.icon ? `${opt.icon} ` : ''}{pick(opt.label)}</option>
        {/each}
      </select>
    {/if}
  {:else if spec.type === 'multi-select'}
    {@render title()}
    <div class={options.some((o) => o.icon) ? 'allergens' : 'chips'}>
      {#each options as opt (opt.value)}
        <button
          type="button"
          class={opt.icon ? 'allergen' : 'chip'}
          class:on={value.includes(opt.value)}
          aria-pressed={value.includes(opt.value)}
          onclick={() => toggle(opt.value)}
        >
          {#if opt.icon}<span class="icon" aria-hidden="true">{opt.icon}</span>{/if}
          <span>{pick(opt.label)}</span>
        </button>
      {/each}
    </div>
  {:else if spec.type === 'lookup'}
    {@render title(id)}
    <LookupField {id} {spec} {labelTypeId} bind:value />
  {/if}
</div>

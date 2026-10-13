<script>
  import { i18n, t } from './i18n.svelte.js'

  // Draws the label on a strip of tape with the printer's blank margins, at physical scale.
  let { src, size } = $props()

  let zoom = $state(false)

  // CSS percentages for padding are relative to the width, so mm / tape width works on both axes.
  const pct = (mm) => `${(mm / size.tape) * 100}%`
  const side = $derived(pct((size.tape - size.printable) / 2))
  const feed = $derived(pct(size.feed))
  const fmt = (mm) => mm.toLocaleString(i18n.locale, { maximumFractionDigits: 0 })
</script>

<div class="label-preview" class:zoom>
  <div class="dim-w"><span>{fmt(size.tape)} mm</span></div>
  <div class="tape-row">
    <div class="tape" style:width={zoom ? '100%' : `${size.tape}mm`} style:padding="{feed} {side}">
      <img {src} alt={t('preview.alt')} />
    </div>
    <div class="dim-h"><span>{fmt(size.length)} mm</span></div>
  </div>
</div>
<button type="button" class="zoom-toggle" onclick={() => (zoom = !zoom)}>
  {zoom ? t('preview.actualSize') : t('preview.zoom')}
</button>

<style>
  .label-preview {
    display: inline-grid;
    max-width: 100%;
    color: var(--muted);
    font-size: 13px;
  }

  .label-preview.zoom { display: grid; }

  .dim-w, .dim-h { display: flex; align-items: center; justify-content: center; }

  .dim-w {
    margin-right: 28px;
    margin-bottom: 6px;
    border-left: 1px solid;
    border-right: 1px solid;
    height: 14px;
    background: linear-gradient(currentColor, currentColor) center / 100% 1px no-repeat;
  }

  .dim-h {
    width: 22px;
    margin-left: 6px;
    border-top: 1px solid;
    border-bottom: 1px solid;
    background: linear-gradient(currentColor, currentColor) center / 1px 100% no-repeat;
  }

  .dim-w span, .dim-h span { background: var(--bg); padding: 0 4px; white-space: nowrap; }
  .dim-h span { writing-mode: vertical-rl; padding: 4px 0; }

  .tape-row { display: flex; justify-content: center; }

  .tape {
    max-width: calc(100% - 28px);
    background: #fff;
    box-shadow: 0 1px 4px rgb(0 0 0 / 0.2);
  }

  .zoom .tape { flex: 1; }

  img { display: block; width: 100%; height: auto; }

  .zoom-toggle {
    display: block;
    margin: 10px auto 0;
    border: 0;
    background: none;
    color: var(--accent);
    font-size: 15px;
    text-decoration: underline;
  }
</style>

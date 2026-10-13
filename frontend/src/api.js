/** Error from the backend. `code`/`params` are translated by errorText() in i18n.svelte.js. */
export class ApiError extends Error {
  constructor(message, code = null, params = {}) {
    super(message)
    this.code = code
    this.params = params
  }
}

async function request(path, options = {}) {
  let res
  try {
    res = await fetch(`/api${path}`, options)
  } catch (e) {
    throw new ApiError(e.message, 'network')
  }
  if (!res.ok) {
    let error = new ApiError(`${res.status} ${res.statusText}`)
    try {
      const { detail } = await res.json()
      if (typeof detail === 'string') error = new ApiError(detail)
      // Coded app error: {code, message, params}
      else if (detail?.code) error = new ApiError(detail.message, detail.code, detail.params)
      // Pydantic validation error: [{type: "invalid_host", msg: "..."}]
      else if (Array.isArray(detail) && detail.length) error = new ApiError(detail[0].msg, detail[0].type)
    } catch {}
    throw error
  }
  return res
}

const send = (method, path, body) =>
  request(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })

const post = (path, body) => send('POST', path, body)

const withParams = (path, params) => {
  const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v != null && v !== ''))
  return `${path}?${q}`
}

export async function getPrinters() {
  return (await request('/printers')).json()
}

export async function getPrinterOptions() {
  return (await request('/printers/options')).json()
}

export async function addPrinter(printer) {
  return (await post('/printers', printer)).json()
}

export async function updatePrinter(id, printer) {
  return (await send('PUT', `/printers/${id}`, printer)).json()
}

export async function deletePrinter(id) {
  return (await request(`/printers/${id}`, { method: 'DELETE' })).json()
}

export async function testPrinter(printer) {
  return (await post('/printers/test', printer)).json()
}

export async function getDefaultSubnet() {
  return (await request('/scan/default')).json()
}

export async function scanPrinters(subnet) {
  return (await post('/scan', { subnet })).json()
}

export async function getLabelTypes() {
  return (await request('/label-types')).json()
}

export async function searchLookup(labelTypeId, fieldId, query, lang) {
  const params = new URLSearchParams({ q: query, lang })
  return (await request(`/label-types/${labelTypeId}/search/${fieldId}?${params}`)).json()
}

export async function previewLabel(labelTypeId, values, lang, printer) {
  const res = await post(withParams(`/preview/${labelTypeId}`, { lang, printer }), values)
  const mm = (name) => Number(res.headers.get(`X-Label-${name}-Mm`))
  const size = { tape: mm('Tape'), printable: mm('Printable'), length: mm('Length'), feed: mm('Feed') }
  return { blob: await res.blob(), size }
}

export async function printLabel(labelTypeId, values, lang, printer, copies = 1) {
  return (await post(withParams(`/print/${labelTypeId}`, { lang, printer, copies }), values)).json()
}

export async function getJobs() {
  return (await request('/jobs')).json()
}

export async function reprintJob(id) {
  return (await post(`/jobs/${id}/reprint`, {})).json()
}

export async function getPrinterStatus() {
  return (await request('/printers/status')).json()
}

export async function getHealth() {
  return (await request('/health')).json()
}

export async function getPlugins() {
  return (await request('/plugins')).json()
}

export async function updatePlugin(pluginId, update) {
  return (await send('PUT', `/plugins/${pluginId}`, update)).json()
}

export async function checkPlugin(pluginId) {
  return (await post(`/plugins/${pluginId}/check`, {})).json()
}

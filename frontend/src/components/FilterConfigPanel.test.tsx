import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api/client'
import { configFixture, schemaFixture } from '../test/fixtures'
import { FilterConfigPanel } from './FilterConfigPanel'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    api: { ...actual.api, patchConfig: vi.fn().mockResolvedValue({}) },
  }
})

const patchConfig = vi.mocked(api.patchConfig)

/** Find the enabled checkbox of a filter row by its visible ordinal.label prefix. */
function enabledCheckbox(labelPrefix: string): HTMLInputElement {
  const row = screen.getByText(new RegExp(labelPrefix)).closest('.filter-row')
  if (!row) throw new Error(`row not found for ${labelPrefix}`)
  return within(row as HTMLElement).getAllByRole('checkbox')[0] as HTMLInputElement
}

beforeEach(() => {
  patchConfig.mockClear()
})

describe('FilterConfigPanel schema rendering', () => {
  it('renders one row per metadata entry from the schema fixture', () => {
    render(<FilterConfigPanel schema={schemaFixture} config={configFixture(true, true)} onChanged={vi.fn()} />)
    expect(screen.getByText(/Cường độ xu hướng \(ADX\)/)).toBeInTheDocument()
    expect(screen.getByText(/Độ mượt xu hướng \(ER\)/)).toBeInTheDocument()
    // The scalar param inputs come from the schema, not hardcoded.
    expect(screen.getByText('threshold_trend')).toBeInTheDocument()
    expect(screen.getByText('threshold')).toBeInTheDocument()
  })
})

describe('fail-open regime guard', () => {
  it('does NOT prompt when only one of the pair is turned off (other still on)', async () => {
    const user = userEvent.setup()
    render(<FilterConfigPanel schema={schemaFixture} config={configFixture(true, true)} onChanged={vi.fn()} />)

    await user.click(enabledCheckbox('Cường độ xu hướng \\(ADX\\)'))

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    await waitFor(() => expect(patchConfig).toHaveBeenCalledWith({ filters: { adx_filter: { enabled: false } } }))
  })

  it('prompts when disabling ADX second (ER already off) and applies on confirm', async () => {
    const user = userEvent.setup()
    // ER already off -> turning ADX off is the second toggle.
    render(<FilterConfigPanel schema={schemaFixture} config={configFixture(true, false)} onChanged={vi.fn()} />)

    await user.click(enabledCheckbox('Cường độ xu hướng \\(ADX\\)'))

    const dialog = await screen.findByRole('dialog')
    expect(dialog).toBeInTheDocument()
    // Nothing applied until the user confirms.
    expect(patchConfig).not.toHaveBeenCalled()

    await user.click(within(dialog).getByRole('button', { name: /Vẫn tắt/ }))
    await waitFor(() => expect(patchConfig).toHaveBeenCalledWith({ filters: { adx_filter: { enabled: false } } }))
  })

  it('prompts when disabling ER second (ADX already off) and cancel keeps it unchanged', async () => {
    const user = userEvent.setup()
    // ADX already off -> turning ER off is the second toggle.
    render(<FilterConfigPanel schema={schemaFixture} config={configFixture(false, true)} onChanged={vi.fn()} />)

    await user.click(enabledCheckbox('Độ mượt xu hướng \\(ER\\)'))

    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: /Huỷ/ }))

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(patchConfig).not.toHaveBeenCalled()
  })
})

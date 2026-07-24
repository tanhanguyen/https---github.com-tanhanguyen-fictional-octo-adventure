import { render, screen } from '@testing-library/react'
import type { ReactElement } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { configFixture } from '../test/fixtures'

// One API mock covering every method the four pages touch on mount. Lists resolve empty
// so each page renders its "no data yet" shell without crashing.
vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    api: {
      ...actual.api,
      listDatasets: vi.fn().mockResolvedValue([]),
      listTrades: vi.fn().mockResolvedValue([]),
      listRuns: vi.fn().mockResolvedValue([]),
      listDecisions: vi.fn().mockResolvedValue([]),
      getDecisionStats: vi.fn().mockResolvedValue({ histogram: {} }),
      getConfig: vi.fn().mockResolvedValue(configFixture(true, true)),
    },
  }
})

import { DatasetsPage } from './DatasetsPage'
import { DecisionsPage } from './DecisionsPage'
import { RunsPage } from './RunsPage'
import { TradesPage } from './TradesPage'

function renderPage(node: ReactElement) {
  return render(<MemoryRouter>{node}</MemoryRouter>)
}

describe('page smoke render', () => {
  it('renders DatasetsPage', async () => {
    renderPage(<DatasetsPage />)
    expect(await screen.findByRole('heading', { name: 'Datasets' })).toBeInTheDocument()
  })

  it('renders TradesPage', async () => {
    renderPage(<TradesPage />)
    expect(await screen.findByRole('table')).toBeInTheDocument()
  })

  it('renders RunsPage', async () => {
    renderPage(<RunsPage />)
    expect(await screen.findByRole('heading', { name: 'Runs' })).toBeInTheDocument()
  })

  it('renders DecisionsPage', async () => {
    renderPage(<DecisionsPage />)
    expect(
      await screen.findByRole('heading', { name: /histogram/i }),
    ).toBeInTheDocument()
  })
})

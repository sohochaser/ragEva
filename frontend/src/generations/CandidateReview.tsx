import { ArrowDown, ArrowUp, Check, Pencil, Plus, RefreshCw, Save, Search, X } from 'lucide-react'
import { useState } from 'react'

import { fetchCollection, type CollectionDetail } from '../api/documentCollections'
import {
  allowSuspectedCandidate, CandidateReviewError, fetchCandidate, fetchCandidateRevisions,
  fetchDuplicateCheck, fetchDuplicateHistory, recheckCandidate, reviewCandidate,
  type CandidateReviewIssue, type CandidateRevision, type DuplicateCheck, type GeneratedCandidate,
} from '../api/generations'
import { uiError } from '../ui/text'

const statusLabels: Record<string, string> = {
  pending_review: 'Pending Review（待审核）', approved: 'Approved（已批准）', rejected: 'Rejected（已驳回）',
}
const fieldLabels: Record<string, string> = {
  question: 'Question（问题）', reference_answer: 'Reference Answer（标准答案）', support_positions: 'Reference Chunks（参考 chunk）', collection_id: 'Document Collection（文档集合）',
}

export function CandidateReview({ candidate, onUpdated }: {
  candidate: GeneratedCandidate
  onUpdated: (candidate: GeneratedCandidate) => void
}) {
  const [open, setOpen] = useState(false)
  const [collection, setCollection] = useState<CollectionDetail | null>(null)
  const [history, setHistory] = useState<CandidateRevision[]>([])
  const [duplicate, setDuplicate] = useState<DuplicateCheck | null>(null)
  const [duplicateHistory, setDuplicateHistory] = useState<DuplicateCheck[]>([])
  const [allowReason, setAllowReason] = useState('')
  const [question, setQuestion] = useState(candidate.question)
  const [answer, setAnswer] = useState(candidate.reference_answer)
  const [positions, setPositions] = useState<number[]>(candidate.support_positions)
  const [nextPosition, setNextPosition] = useState('')
  const [issues, setIssues] = useState<CandidateReviewIssue[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function load() {
    setBusy(true)
    setError('')
    try {
      const [source, revisions, check, checks] = await Promise.all([
        fetchCollection(candidate.collection_id), fetchCandidateRevisions(candidate.id),
        fetchDuplicateCheck(candidate.id), fetchDuplicateHistory(candidate.id),
      ])
      setCollection(source)
      setHistory(revisions)
      setDuplicate(check)
      setDuplicateHistory(checks)
      setQuestion(candidate.question)
      setAnswer(candidate.reference_answer)
      setPositions(candidate.support_positions)
      setIssues([])
      setOpen(true)
    } catch (cause) {
      setError(uiError(cause, 'Unable to load review data', '审核数据加载失败'))
    } finally { setBusy(false) }
  }

  async function refresh() {
    setBusy(true)
    try {
      const [updated, revisions, check, checks] = await Promise.all([
        fetchCandidate(candidate.id), fetchCandidateRevisions(candidate.id),
        fetchDuplicateCheck(candidate.id), fetchDuplicateHistory(candidate.id),
      ])
      onUpdated(updated)
      setQuestion(updated.question)
      setAnswer(updated.reference_answer)
      setPositions(updated.support_positions)
      setHistory(revisions)
      setDuplicate(check)
      setDuplicateHistory(checks)
      setIssues([])
      setError('')
    } catch (cause) {
      setError(uiError(cause, 'Refresh failed', '刷新失败'))
    } finally { setBusy(false) }
  }

  function move(index: number, direction: number) {
    const next = [...positions]
    const other = index + direction
    if (other < 0 || other >= next.length) return
    const before = next[index]
    next[index] = next[other]
    next[other] = before
    setPositions(next)
  }

  async function submit(action: 'save' | 'approve' | 'reject') {
    setBusy(true)
    setError('')
    setIssues([])
    try {
      const updated = await reviewCandidate(candidate.id, {
        expected_revision: candidate.revision,
        collection_id: candidate.collection_id,
        question,
        reference_answer: answer,
        support_positions: positions,
        action,
      })
      onUpdated(updated)
      setHistory(await fetchCandidateRevisions(candidate.id))
      setDuplicate(await fetchDuplicateCheck(candidate.id))
      setDuplicateHistory(await fetchDuplicateHistory(candidate.id))
      setAllowReason('')
    } catch (cause) {
      if (cause instanceof CandidateReviewError) setIssues(cause.issues)
      else setError(uiError(cause, 'Candidate review failed', '候选审核失败'))
    } finally { setBusy(false) }
  }

  async function recheck() {
    setBusy(true)
    setError('')
    try {
      setDuplicate(await recheckCandidate(candidate.id))
      setDuplicateHistory(await fetchDuplicateHistory(candidate.id))
      setAllowReason('')
    } catch (cause) {
      setError(uiError(cause, 'Duplicate check failed', '查重失败'))
    } finally { setBusy(false) }
  }

  async function allow() {
    if (!duplicate) return
    setBusy(true)
    setError('')
    try {
      setDuplicate(await allowSuspectedCandidate(candidate.id, duplicate, allowReason.trim()))
      setDuplicateHistory(await fetchDuplicateHistory(candidate.id))
      setAllowReason('')
    } catch (cause) {
      setError(uiError(cause, 'Override failed', '放行失败'))
    } finally { setBusy(false) }
  }

  const selected = positions.map((position) => collection?.chunks.find((chunk) => chunk.position === position))
  const available = collection?.chunks.filter((chunk) => !positions.includes(chunk.position)) ?? []

  return <div className="candidate-review">
    <div className="candidate-review-toolbar"><span className={`review-status review-status-${candidate.status}`}>{statusLabels[candidate.status] ?? candidate.status}</span>
      <button type="button" className="secondary-button" onClick={() => open ? setOpen(false) : void load()} disabled={busy}><Pencil size={14} />{open ? 'Close Review（收起审核）' : 'Review（审核）'}</button>
    </div>
    {error && <div className="form-error" role="alert">{error}{open && <button type="button" className="icon-button" title="Refresh Candidates（刷新候选）" aria-label="Refresh Candidates（刷新候选）" onClick={() => void refresh()}><RefreshCw size={15} /></button>}</div>}
    {open && collection && <div className="candidate-review-form">
      <div className="candidate-review-fields">
        <label className="form-group"><span className="form-label">Question（问题）</span><textarea value={question} maxLength={2000} onChange={(event) => setQuestion(event.target.value)} /></label>
        <label className="form-group"><span className="form-label">Reference Answer（标准答案）</span><textarea value={answer} maxLength={10000} onChange={(event) => setAnswer(event.target.value)} /></label>
      </div>
      <div className="candidate-review-sources"><h4>Reference Chunks（参考 chunk）</h4>
        <ol>{positions.map((position, index) => { const chunk = selected[index]; return <li key={position}>
          <div><span>#{index + 1}</span><code>{chunk?.document_id}</code><p>{chunk?.text}</p></div>
          <div className="candidate-review-tools"><button type="button" className="icon-button" title="Move Up（上移）" aria-label={`Move chunk ${index + 1} up（第 ${index + 1} 个切块上移）`} disabled={index === 0 || busy} onClick={() => move(index, -1)}><ArrowUp size={15} /></button><button type="button" className="icon-button" title="Move Down（下移）" aria-label={`Move chunk ${index + 1} down（第 ${index + 1} 个切块下移）`} disabled={index === positions.length - 1 || busy} onClick={() => move(index, 1)}><ArrowDown size={15} /></button><button type="button" className="icon-button" title="Remove（移除）" aria-label={`Remove chunk ${index + 1}（移除第 ${index + 1} 个切块）`} disabled={busy} onClick={() => setPositions((items) => items.filter((item) => item !== position))}><X size={15} /></button></div>
        </li> })}</ol>
        <div className="candidate-review-add"><select aria-label="Add Reference Chunk（添加参考 chunk）" value={nextPosition} onChange={(event) => setNextPosition(event.target.value)}><option value="">Select Collection Chunk（选择集合 chunk）</option>{available.map((chunk) => <option key={chunk.position} value={chunk.position}>#{chunk.position + 1} · {chunk.document_id} · {chunk.text.slice(0, 70)}</option>)}</select><button type="button" className="secondary-button" disabled={!nextPosition || busy} onClick={() => { setPositions((items) => [...items, Number(nextPosition)]); setNextPosition('') }}><Plus size={14} />Add（添加）</button></div>
      </div>
      {issues.length > 0 && <ul className="candidate-review-issues" role="alert">{issues.map((issue, index) => <li key={`${issue.field}-${index}`}>{fieldLabels[issue.field] ?? issue.field}: {issue.message}</li>)}</ul>}
      <div className="candidate-review-actions"><button type="button" className="secondary-button" disabled={busy} onClick={() => void submit('save')}><Save size={14} />Save Revision（保存修订）</button><button type="button" className="secondary-button" disabled={busy} onClick={() => void submit('reject')}><X size={14} />Reject（驳回）</button><button type="button" className="primary-button" disabled={busy} onClick={() => void submit('approve')}><Check size={14} />Approve（批准）</button></div>
      <section className="candidate-duplicate" aria-label="Collection Duplicate Check（同集合查重）">
        <div className="candidate-duplicate-heading"><h4>Collection Duplicate Check（同集合查重）</h4><button type="button" className="secondary-button" disabled={busy} onClick={() => void recheck()}><Search size={14} />Recheck Duplicates（重新查重）</button></div>
        <p className={`duplicate-verdict duplicate-verdict-${duplicate?.verdict ?? 'missing'}`}>
          {duplicate?.verdict === 'duplicate' ? 'Confirmed Duplicate（明确重复） · Cannot Publish（不可发布）' : duplicate?.verdict === 'suspected' ? (duplicate.decision === 'allow' ? 'Suspected Duplicate（疑似重复） · Override Approved（已放行）' : 'Suspected Duplicate（疑似重复） · Awaiting Decision（待确认）') : duplicate?.verdict === 'unique' ? 'No Duplicates Found（未发现重复）' : 'No Current Duplicate Check（尚无有效查重结果）'}
        </p>
        {duplicate && <><p className="candidate-duplicate-meta">Revision #（修订 #）{duplicate.revision} · {new Date(duplicate.checked_at).toLocaleString()}</p>
          {duplicate.matches.length > 0 && <ul className="candidate-duplicate-matches">{duplicate.matches.map((match) => <li key={`${match.source_kind}-${match.source_id}`}>
            <strong>{match.verdict === 'duplicate' ? 'Confirmed Duplicate（明确重复）' : 'Suspected Duplicate（疑似重复）'}</strong><span>{match.source_kind === 'published_case' ? 'Published Case（已发布样本）' : 'Candidate（候选）'} · {match.source_id}</span>
            <p>{match.question}</p><p>Answer（答案）：{match.reference_answer}</p><small>Shared Sources（共同来源） {match.shared_source_count} · Question Similarity（问题相似度） {Math.round(match.question_similarity * 100)}%</small>
          </li>)}</ul>}
          {duplicate.verdict === 'suspected' && duplicate.decision !== 'allow' && candidate.status === 'approved' && <div className="candidate-duplicate-allow"><label className="form-group"><span className="form-label">Reason for Duplicate Override（非重复放行理由）</span><textarea value={allowReason} maxLength={2000} onChange={(event) => setAllowReason(event.target.value)} /></label><button type="button" className="secondary-button" disabled={busy || !allowReason.trim()} onClick={() => void allow()}><Check size={14} />Confirm Override（确认放行）</button></div>}
          {duplicate.decision === 'allow' && <p className="candidate-duplicate-reason">Override Reason（放行理由）：{duplicate.reason}</p>}
        </>}
        {duplicateHistory.length > 0 && <details className="candidate-duplicate-history"><summary>Duplicate Check History（查重记录） · {duplicateHistory.length}</summary><ol>{duplicateHistory.map((check) => <li key={check.id}>Revision #（修订 #）{check.revision} · {check.verdict === 'duplicate' ? 'Confirmed Duplicate（明确重复）' : check.verdict === 'suspected' ? 'Suspected Duplicate（疑似重复）' : 'No Duplicates Found（未发现重复）'} · {new Date(check.checked_at).toLocaleString()}{check.decision === 'allow' && <p>Override Approved（已放行）：{check.reason}</p>}</li>)}</ol></details>}
      </section>
      <details className="candidate-review-history"><summary>Revision History（修订记录） · {history.length}</summary><ol>{history.map((revision) => <li key={revision.revision}><span>#{revision.revision} · {statusLabels[revision.status] ?? revision.status}</span><time>{new Date(revision.created_at).toLocaleString()}</time><p>{revision.question || 'Empty Question（空问题）'}</p><p>{revision.reference_answer || 'Empty Answer（空答案）'}</p><ul>{revision.reference_chunks.map((chunk, index) => <li key={`${revision.revision}-${index}`}><code>{chunk.document_id}</code> · {chunk.text}</li>)}</ul></li>)}</ol></details>
    </div>}
  </div>
}

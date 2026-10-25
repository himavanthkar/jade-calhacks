import { ApiError, errorKind } from './api'
import './ErrorNotice.css'

/** One place that tells a refusal by policy (SoD, a gate) apart from a failed request. */
export default function ErrorNotice({error,onRetry,retryLabel='Retry'}:{error:unknown;onRetry?:()=>void;retryLabel?:string}) {
  if(!error)return null
  const message=error instanceof Error?error.message:String(error)
  const kind=errorKind(error)
  const status=error instanceof ApiError?error.status:undefined
  if(kind==='segregation_of_duties')return <section className="refusal sod" role="alert"><p className="eyebrow">BLOCKED · SEGREGATION OF DUTIES</p><h3>This person can't approve it</h3><p>{message}</p><small>The attempt is on the record as a finding. Nothing was posted.</small></section>
  if(kind==='gate_failure')return <section className="refusal gate" role="alert"><p className="eyebrow">BLOCKED · VERIFICATION GATE</p><h3>The period can't move until the gate passes</h3><p>{message}</p>{onRetry&&<button onClick={onRetry}>{retryLabel}</button>}</section>
  if(status===403)return <section className="refusal" role="alert"><p className="eyebrow">NOT PERMITTED</p><p>{message}</p></section>
  if(status===409||status===422)return <section className="refusal" role="alert"><p className="eyebrow">REFUSED · {status}</p><p>{message}</p>{onRetry&&<button onClick={onRetry}>{retryLabel}</button>}</section>
  return <div className="error" role="alert">{message} {onRetry&&<button onClick={onRetry}>{retryLabel}</button>}</div>
}

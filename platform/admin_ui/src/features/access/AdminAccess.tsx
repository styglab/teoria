import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { adminApi } from "../../api/admin";

type Principal = { actor: string; roles: string[] };
const AccessContext = createContext<{ principal: Principal | null; requestLogin: () => void }>({principal:null,requestLogin:()=>{}});
export const useAdminAccess = () => useContext(AccessContext);
export function AdminAccessProvider({children}:{children:ReactNode}) {
 const [principal,setPrincipal]=useState<Principal|null>(null);
 const [open,setOpen]=useState(false);
 const [token,setToken]=useState("");
 const [busy,setBusy]=useState(false);
 const [error,setError]=useState<string|null>(null);
 const [visible,setVisible]=useState(false);
 useEffect(()=>{
  if(window.sessionStorage.getItem("teoria-admin-token")) adminApi.session().then(setPrincipal).catch(()=>window.sessionStorage.removeItem("teoria-admin-token"));
 },[]);
 const close=()=>{if(!busy){setOpen(false);setToken("");setError(null);setVisible(false)}};
 return <AccessContext.Provider value={{principal,requestLogin:()=>setOpen(true)}}>
 {children}
 <div className="admin-session-control">{principal ? <><span>관리자 · {principal.actor}</span><button onClick={()=>{window.sessionStorage.removeItem("teoria-admin-token");setPrincipal(null)}}>로그아웃</button></> : <><span>조회 모드</span><button onClick={()=>setOpen(true)}>관리자 연결</button></>}</div>
 {open && <div className="validation-backdrop"><section className="admin-login-dialog" role="dialog" aria-modal="true" aria-label="관리자 연결">
 <h2>관리자 연결</h2><p>조회는 토큰 없이 가능합니다. 변경 작업에는 관리자 인증이 필요합니다.</p>
 <form onSubmit={async event=>{
  event.preventDefault();if(busy)return;
  let value=token.trim().replace(/^(?:export\s+)?TEORIA_ADMIN_API_TOKEN\s*=\s*/,"");
  if((value.startsWith('"')&&value.endsWith('"'))||(value.startsWith("'")&&value.endsWith("'")))value=value.slice(1,-1);
  value=value.replace(/^Bearer\s+/i,"").trim();if(!value)return;
  setBusy(true);setError(null);window.sessionStorage.setItem("teoria-admin-token",value);
  try {setPrincipal(await adminApi.session());setOpen(false);setToken("");setVisible(false)}
  catch(reason){window.sessionStorage.removeItem("teoria-admin-token");setPrincipal(null);setError((reason as Error).message.includes("(401)")?"운영 서버가 토큰을 거절했습니다. Teoria 관리자 토큰인지 확인하세요.":"인증 서버에 연결하지 못했습니다. 다시 시도하세요.")}
  finally{setBusy(false)}
 }}><label>관리자 토큰<input type={visible?"text":"password"} autoComplete="off" disabled={busy} value={token} onChange={event=>setToken(event.target.value)}/></label>
 <div className="page-actions"><button type="button" disabled={busy} onClick={()=>setVisible(value=>!value)}>{visible?"토큰 숨기기":"토큰 보기"}</button><button type="button" disabled={busy} onClick={close}>취소</button><button type="submit" disabled={busy||!token.trim()}>{busy?"연결 중…":"연결"}</button></div>
 {error&&<p role="alert">{error}</p>}</form></section></div>}
 </AccessContext.Provider>;
}
export function AdminAccess({children}:{children:ReactNode}) {
 const {principal,requestLogin}=useAdminAccess();
 if(!principal)return <div className="workspace-empty"><h2>관리자 연결이 필요합니다</h2><p>검토·승인·업무 의미 관리에는 인증된 관리자가 필요합니다.</p><button onClick={requestLogin}>관리자 연결</button></div>;
 return <>{children}</>;
}

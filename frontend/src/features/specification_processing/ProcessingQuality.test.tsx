import { cleanup,render,screen } from '@testing-library/react';
import { afterEach,expect,it } from 'vitest';
import { RunQuality,VersionQuality } from './ProcessingQuality';
afterEach(cleanup);
it('shows automatic hold reasons and distinguishes missing historical measurements',()=>{
 render(<><RunQuality summary={{quality:{validation_errors:1,quarantined_attributes:1,failed_document_ratio:0},
   automatic_application_standard:{quality_gate:{reasons:['source_validation_errors'],attribute_count_change_ratio:null}}}}/>
  <VersionQuality versions={[{processor_revision:null,model_requested:null,runs:1,measured_runs:0,approved:0,held:0,validation_errors:0,accepted_attributes:0,quarantined_attributes:0,applied_attributes:0,held_attributes:0}]}/></>);
 expect(screen.getByText('自动 승인 보류 사유: 원문 검증 오류'.replace('自动','자동'))).toBeTruthy();
 expect(screen.getAllByText('측정 없음').length).toBe(2);
});

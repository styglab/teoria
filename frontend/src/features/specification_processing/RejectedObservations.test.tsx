import { cleanup,fireEvent,render,screen } from '@testing-library/react';
import { afterEach,expect,it,vi } from 'vitest';
import { RejectedObservations } from './RejectedObservations';
import { processingApi } from '../../api/specification_processing';
afterEach(()=>{cleanup();vi.restoreAllMocks();});
it('shows rejected values beside original text and replays the stored validator',async()=>{
  const replay=vi.spyOn(processingApi,'reproduceValidation').mockResolvedValue({verdict:'rejected',code:'source_numeric_literal_mismatch',model_called:false});
  const source=vi.fn();
  render(<RejectedObservations document={{document_id:'doc',quarantined_attributes:[{
    attribute:{id:'a',property_raw:'프로그램 수',value_raw:'10',unit_raw:'개'},issue:{code:'source_numeric_literal_mismatch'}}]}}
    runId='run' onSource={source} sourceText={()=>'프로그램: 100개 저장'}/>);
  expect(screen.getByText('프로그램: 100개 저장')).toBeTruthy();
  fireEvent.click(screen.getByRole('button',{name:'원문 위치 확인'}));expect(source).toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button',{name:'현재 기준으로 다시 검사'}));
  expect(await screen.findByRole('status')).toHaveProperty('textContent','추출한 숫자가 원문의 완전한 숫자와 다릅니다');
  expect(replay).toHaveBeenCalledWith('run','doc','a');
});

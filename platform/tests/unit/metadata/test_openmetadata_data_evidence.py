from unittest.mock import AsyncMock

import pytest

from teoria.metadata.openmetadata.client import OpenMetadataClient, OpenMetadataError
from teoria.metadata.openmetadata.service import OpenMetadataService


@pytest.fixture
def service():
    client=OpenMetadataClient('https://example.test/api','token',timeout_seconds=2,verify_ssl=True)
    return OpenMetadataService(client,base_url=client.base_url,database_service='test')


def table(**extra):
    return {'id':'table-1','name':'customers','fullyQualifiedName':'service.db.schema.customers',**extra}


@pytest.mark.asyncio
async def test_samples_are_bounded_masked_and_nulls_preserved(service):
    service.client.get_table_sample_data=AsyncMock(return_value=table(sampleData={
        'columns':['identifier','note'],'rows':[['synthetic-private',None],['another','long note']]}))
    result=await service.get_table_samples('table-1',limit=1)
    assert result.rows==[['[REDACTED]',None]]
    assert result.truncated and result.stored_row_count==2
    assert 'synthetic-private' not in result.model_dump_json()
    assert result.scope=='stored_sample'


@pytest.mark.asyncio
async def test_explicit_sample_values_remain_bounded_and_nested_data_is_hidden(service):
    service.client.get_table_sample_data=AsyncMock(return_value=table(sampleData={
        'columns':['text','nested'],'rows':[['a'*600,{'person':'synthetic-secret'}]]}))
    result=await service.get_table_samples('table-1',include_values=True)
    assert result.values_included and result.truncated
    assert len(result.rows[0][0])==500
    assert result.rows[0][1]=='[STRUCTURED VALUE]'


@pytest.mark.asyncio
async def test_no_samples_is_different_from_an_empty_collected_sample(service):
    service.client.get_table_sample_data=AsyncMock(return_value=table())
    assert (await service.get_table_samples('table-1')).reason=='not_collected'
    service.client.get_table_sample_data=AsyncMock(return_value=table(sampleData={'columns':['x'],'rows':[]}))
    assert (await service.get_table_samples('table-1')).available


@pytest.mark.asyncio
async def test_sample_shape_error_is_not_silently_zipped_or_empty(service):
    service.client.get_table_sample_data=AsyncMock(return_value=table(sampleData={'columns':['x'],'rows':[['x','y']]}))
    with pytest.raises(OpenMetadataError): await service.get_table_samples('table-1')


@pytest.mark.asyncio
async def test_profiles_keep_aggregate_counts_and_omit_source_values(service):
    service.client.get_table_by_id=AsyncMock(return_value=table())
    service.client.get_latest_table_profile=AsyncMock(return_value=table(
        profile={'rowCount':100,'columnCount':2,'customMetrics':[{'secret':'value'}]},
        columns=[{'name':'identifier','profile':{'nullCount':0,'distinctCount':100,'min':'synthetic-id',
                                                 'topValues':['synthetic-private']}},
                 {'name':'nested','children':[{'name':'field','profile':{'maxLength':10}}]}]))
    result=await service.get_table_profile('table-1')
    service.client.get_latest_table_profile.assert_awaited_once_with('service.db.schema.customers')
    assert result.table_metrics=={'rowCount':100,'columnCount':2}
    assert result.column_metrics[0]['metrics']=={'nullCount':0,'distinctCount':100}
    assert result.column_metrics[1]['name']=='nested.field'
    assert 'synthetic-private' not in result.model_dump_json()


@pytest.mark.asyncio
async def test_profile_absence_and_permission_error_are_distinct(service):
    service.client.get_table_by_id=AsyncMock(return_value=table())
    service.client.get_latest_table_profile=AsyncMock(return_value=table(profile=None,columns=[]))
    assert (await service.get_table_profile('table-1')).reason=='not_collected'
    service.client.get_latest_table_profile=AsyncMock(side_effect=OpenMetadataError('openmetadata_api_error','denied',status_code=403))
    with pytest.raises(OpenMetadataError) as exc: await service.get_table_profile('table-1')
    assert exc.value.status_code==403


@pytest.mark.asyncio
async def test_client_uses_id_for_samples_and_encoded_fqn_for_profile(service):
    service.client.get=AsyncMock(return_value={})
    await service.client.get_table_sample_data('id/unsafe')
    service.client.get.assert_awaited_with('v1/tables/id%2Funsafe/sampleData')
    await service.client.get_latest_table_profile('a.b/c')
    service.client.get.assert_awaited_with('v1/tables/a.b%2Fc/tableProfile/latest',params={'includeColumnProfile':'true'})


@pytest.mark.asyncio
async def test_data_evidence_rejects_another_tables_response(service):
    service.client.get_table_sample_data=AsyncMock(return_value=table(id='other-table'))
    with pytest.raises(OpenMetadataError,match='identity'): await service.get_table_samples('table-1')

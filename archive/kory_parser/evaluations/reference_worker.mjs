// Development-only reference executor. Never imported by the parsing library.
import { readFile, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { performance } from 'node:perf_hooks';

const config = JSON.parse(await readFile(process.argv[2], 'utf8'));
const pkg = JSON.parse(await readFile(join(config.reference_package, 'package.json'), 'utf8'));
if (pkg.name !== 'kordoc' || pkg.version !== config.reference_version) throw new Error('Reference version mismatch');
const { parse } = await import(pathToFileURL(join(config.reference_package, 'dist/index.js')).href);
const data = await readFile(config.source);
const options = {ocr:false, formulaOcr:false, images:false, removeHeaderFooter:false, dedupeRunningHeaders:false};
if (['hwp','hwpx'].includes(config.format)) {
  Object.assign(options,{layoutTables:'keep',keepTrailingEmptyCols:true,keepEmptyParagraphs:true});
}
async function execute() {
  try { return await parse(data,options); }
  catch(error) { return {success:false,code:'REFERENCE_EXCEPTION',exception_type:error?.name}; }
}
await execute(); // Warm-up is separate from the reported measurements.
const seconds=[];
let result;
for(let i=0;i<config.repetitions;i++) {
  const started=performance.now();
  result=await execute();
  seconds.push((performance.now()-started)/1000);
}
await writeFile(config.output,JSON.stringify(result));
await writeFile(config.measurement,JSON.stringify({seconds,options,version:pkg.version,node:process.version}));

const fs = require('node:fs');
const path = require('node:path');
const root = __dirname;
const data = JSON.parse(fs.readFileSync(path.join(root, 'catalog.json'), 'utf8'));
if (new Set(data.projects.map(project => project.name)).size !== data.projects.length) throw new Error('Duplicate projects');
const template = fs.readFileSync(path.join(root, 'catalog.template.html'), 'utf8');
fs.writeFileSync(path.join(root, 'index.html'), template.replace('__CATALOG_DATA__', JSON.stringify(data).replace(/</g, '\\u003c')));
console.log('Built ' + data.projects.length + ' projects.');

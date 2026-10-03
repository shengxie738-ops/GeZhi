import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const root=new URL('../',import.meta.url);
for(const file of ['StudentForum','TeacherForumManager']){
 const source=readFileSync(new URL(`js/components/${file}.js`,root),'utf8');
 assert.match(source,/from ['"]\.\.\/utils\/forumIdentity\.js['"]/);
 assert.match(source,/resolveForumAvatar\(/);
 assert.match(source,/@error="onForumAvatarError\(\$event\)"/);
 assert.doesNotMatch(source,/dicebear|toBackendAssetUrl|localhost:8000/);
}
const svg=readFileSync(new URL('assets/avatars/forum-default.svg',root),'utf8');
assert.match(svg,/<svg/);assert.doesNotMatch(svg.replace(/xmlns="http:\/\/www\.w3\.org\/2000\/svg"/,''),/<script|<image|<text|href=|url\(|https?:/i);
console.log('studentForumAvatar local-boundary tests passed');

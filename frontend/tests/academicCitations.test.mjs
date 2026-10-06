import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
    formatBibtex,
    formatRis,
    buildCitationFilename,
    copyCitation,
    downloadCitation
} from '../js/api/academic/citations.js';
import { createAcademicPaper } from '../js/api/academic/paperModel.js';

test('academicCitations: formatBibtex correctly maps workType to BibTeX entry types', () => {
    const journalPaper = createAcademicPaper({
        title: 'Deep Residual Learning',
        authors: ['Kaiming He', 'Xiangyu Zhang'],
        year: 2016,
        venue: 'IEEE CVPR',
        workType: 'journal-article',
        doi: '10.1109/cvpr.2016.90'
    });
    const bibJournal = formatBibtex(journalPaper);
    assert.ok(bibJournal.startsWith('@article{'), 'journal-article should map to @article');
    assert.ok(bibJournal.includes('journal = {IEEE CVPR}'));

    const confPaper = createAcademicPaper({
        title: 'Attention Is All You Need',
        authors: ['Ashish Vaswani', 'Noam Shazeer'],
        year: 2017,
        venue: 'NeurIPS',
        workType: 'conference-paper',
        doi: '10.48550/arxiv.1706.03762'
    });
    const bibConf = formatBibtex(confPaper);
    assert.ok(bibConf.startsWith('@inproceedings{'), 'conference-paper should map to @inproceedings');
    assert.ok(bibConf.includes('booktitle = {NeurIPS}'));

    const preprint = createAcademicPaper({
        title: 'Language Models are Few-Shot Learners',
        authors: ['Tom B. Brown'],
        year: 2020,
        venue: 'arXiv',
        workType: 'preprint',
        arxivId: '2005.14165'
    });
    const bibPreprint = formatBibtex(preprint);
    assert.ok(bibPreprint.startsWith('@misc{'), 'preprint should map to @misc');

    const bookPaper = createAcademicPaper({
        title: 'Deep Learning',
        authors: ['Ian Goodfellow', 'Yoshua Bengio'],
        year: 2016,
        publisher: 'MIT Press',
        workType: 'book'
    });
    const bibBook = formatBibtex(bookPaper);
    assert.ok(bibBook.startsWith('@book{'), 'book should map to @book');
    assert.ok(bibBook.includes('publisher = {MIT Press}'));

    const thesisPaper = createAcademicPaper({
        title: 'Foundations of Cryptography',
        authors: ['Oded Goldreich'],
        year: 1989,
        venue: 'MIT',
        workType: 'thesis'
    });
    const bibThesis = formatBibtex(thesisPaper);
    assert.ok(bibThesis.startsWith('@phdthesis{'), 'thesis should map to @phdthesis');
    assert.ok(bibThesis.includes('school = {MIT}'));
});

test('academicCitations: formatBibtex omits missing fields and sanitizes citation key', () => {
    const minimal = createAcademicPaper({
        title: 'Minimal Paper With No Meta',
        authors: []
        // Missing year, venue, doi, officialUrl
    });

    const bib = formatBibtex(minimal);
    assert.ok(bib.includes('title = {Minimal Paper With No Meta}'));
    assert.ok(!bib.includes('year ='), 'Should omit year field');
    assert.ok(!bib.includes('doi ='), 'Should omit doi field');
    assert.ok(!bib.includes('journal ='), 'Should omit journal field');
    assert.ok(!bib.includes('booktitle ='), 'Should omit booktitle field');
    assert.ok(!bib.includes('url ='), 'Should omit url field');

    // Citation key must only contain ASCII alphanumeric and underscore
    const keyMatch = bib.match(/@\w+\{([^,]+),/);
    assert.ok(keyMatch, 'Should find citation key');
    assert.match(keyMatch[1], /^[a-zA-Z0-9_]+$/, 'Key should only contain ASCII alphanumeric and underscore');
});

test('academicCitations: formatBibtex properly escapes special TeX characters', () => {
    const special = createAcademicPaper({
        title: 'Analysis of 100% & 50$ of C# _under_ {braces} ~tilde~ ^hat^ \\slash',
        authors: ['M & M', 'Dollar $ Bill'],
        year: 2024,
        workType: 'journal-article'
    });

    const bib = formatBibtex(special);
    assert.ok(bib.includes('\\%'), '% should be escaped');
    assert.ok(bib.includes('\\&'), '& should be escaped');
    assert.ok(bib.includes('\\$'), '$ should be escaped');
    assert.ok(bib.includes('\\#'), '# should be escaped');
    assert.ok(bib.includes('\\_'), '_ should be escaped');
    assert.ok(bib.includes('\\{'), '{ should be escaped');
    assert.ok(bib.includes('\\}'), '} should be escaped');
    assert.ok(bib.includes('\\textasciitilde{}'), '~ should be escaped');
    assert.ok(bib.includes('\\textasciicircum{}'), '^ should be escaped');
    assert.ok(bib.includes('\\textbackslash{}'), '\\ should be escaped');
});

test('academicCitations: formatRis correctly maps types and outputs separate AU fields', () => {
    const paper = createAcademicPaper({
        title: 'Attention Is All You Need',
        authors: ['Ashish Vaswani', 'Noam Shazeer', 'Niki Parmar'],
        year: 2017,
        venue: 'NeurIPS',
        workType: 'conference-paper',
        doi: '10.48550/arxiv.1706.03762',
        officialUrl: 'https://doi.org/10.48550/arxiv.1706.03762',
        abstract: 'The dominant sequence transduction models...'
    });

    const ris = formatRis(paper);
    assert.ok(ris.includes('TY  - CPAPER'), 'conference-paper should map to CPAPER');
    assert.ok(ris.includes('TI  - Attention Is All You Need'), 'Title should be present');
    assert.ok(ris.includes('AU  - Ashish Vaswani\n'), 'Author 1 should have separate AU');
    assert.ok(ris.includes('AU  - Noam Shazeer\n'), 'Author 2 should have separate AU');
    assert.ok(ris.includes('AU  - Niki Parmar\n'), 'Author 3 should have separate AU');
    assert.ok(ris.includes('PY  - 2017'), 'Year should be mapped to PY');
    assert.ok(ris.includes('DO  - 10.48550/arxiv.1706.03762'), 'DOI mapped to DO');
    assert.ok(ris.includes('UR  - https://doi.org/10.48550/arxiv.1706.03762'), 'URL mapped to UR');
    assert.ok(ris.includes('AB  - The dominant sequence transduction models...'), 'Abstract mapped to AB');
    assert.ok(ris.endsWith('ER  - \n') || ris.endsWith('ER  -'), 'Should end with ER  -');

    // Test journal-article -> JOUR, preprint -> RPRT
    const journalPaper = createAcademicPaper({ title: 'J', workType: 'journal-article' });
    assert.ok(formatRis(journalPaper).includes('TY  - JOUR'));

    const preprintPaper = createAcademicPaper({ title: 'P', workType: 'preprint' });
    assert.ok(formatRis(preprintPaper).includes('TY  - RPRT'));
});

test('academicCitations: buildCitationFilename sanitizes Windows illegal characters', () => {
    const dirtyPaper = createAcademicPaper({
        title: 'Is "AI" <better> than Humans: A Survey / Review? *Yes* | No\\Maybe',
        authors: ['Vaswani, A.'],
        year: 2024
    });

    const filenameBib = buildCitationFilename(dirtyPaper, 'bib');
    assert.ok(!/[<>:"/\\|?*]/.test(filenameBib), 'Filename must not contain illegal Windows characters');
    assert.ok(filenameBib.endsWith('.bib'), 'Filename must end with .bib');

    const filenameRis = buildCitationFilename(dirtyPaper, 'ris');
    assert.ok(!/[<>:"/\\|?*]/.test(filenameRis), 'Filename must not contain illegal Windows characters');
    assert.ok(filenameRis.endsWith('.ris'), 'Filename must end with .ris');
});

test('academicCitations: copyCitation and downloadCitation execute safely', async () => {
    let clipboardText = '';
    if (typeof navigator !== 'undefined') {
        Object.defineProperty(navigator, 'clipboard', {
            value: {
                writeText: async (t) => { clipboardText = t; }
            },
            configurable: true,
            writable: true
        });
    }

    const paper = createAcademicPaper({ title: 'Test Paper', year: 2024 });
    const success = await copyCitation(formatBibtex(paper));
    assert.equal(success, true);
    assert.ok(clipboardText.includes('Test Paper'));

    // Test downloadCitation in Node environment gracefully handles lack of window.document
    assert.doesNotThrow(() => {
        downloadCitation(paper, 'bib');
    });
});

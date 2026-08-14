import { execFile } from 'node:child_process';
import { createReadStream } from 'node:fs';
import { stat } from 'node:fs/promises';
import { createServer } from 'node:http';
import { createRequire } from 'node:module';
import path from 'node:path';
import { promisify } from 'node:util';

const requireFromRuntime = createRequire(
  path.join(path.dirname(process.execPath), '..', 'runtime-entry.cjs')
);
const { chromium } = requireFromRuntime('playwright');
const execFileAsync = promisify(execFile);

const PX_PER_MM = 96 / 25.4;
const A4_WIDTH_MM = 210;
const A4_HEIGHT_MM = 297;
const MM_TOLERANCE = 0.6;
const PAGE_OVERFLOW_TOLERANCE = 8;
const VIEWPORT = { width: 1440, height: 1200 };
const EMPTY_PDF_NAME = 'resume-empty-photo.pdf';
const PHOTO_PDF_NAME = 'resume-test-photo.pdf';

function fail(message) {
  throw new Error(message);
}

function check(condition, message) {
  if (!condition) fail(message);
}

function parseArguments(argv) {
  const required = new Set([
    '--html',
    '--out-dir',
    '--browser-executable',
    '--pdfinfo',
  ]);
  const values = new Map();

  for (let index = 0; index < argv.length; index += 2) {
    const name = argv[index];
    const value = argv[index + 1];
    if (!required.has(name)) fail(`unknown argument: ${name ?? '(missing)'}`);
    if (!value || value.startsWith('--')) fail(`missing value for ${name}`);
    if (values.has(name)) fail(`duplicate argument: ${name}`);
    values.set(name, path.resolve(value));
  }

  for (const name of required) {
    if (!values.has(name)) fail(`missing required argument: ${name}`);
  }

  return {
    html: values.get('--html'),
    outDir: values.get('--out-dir'),
    browserExecutable: values.get('--browser-executable'),
    pdfinfo: values.get('--pdfinfo'),
  };
}

async function validatePath(targetPath, kind, label) {
  let details;
  try {
    details = await stat(targetPath);
  } catch (error) {
    fail(`${label} does not exist: ${targetPath}`);
  }
  if (kind === 'file') check(details.isFile(), `${label} is not a file: ${targetPath}`);
  if (kind === 'directory') {
    check(details.isDirectory(), `${label} is not a directory: ${targetPath}`);
  }
}

function contentType(filePath) {
  const extension = path.extname(filePath).toLowerCase();
  return {
    '.css': 'text/css; charset=utf-8',
    '.html': 'text/html; charset=utf-8',
    '.jpeg': 'image/jpeg',
    '.jpg': 'image/jpeg',
    '.js': 'text/javascript; charset=utf-8',
    '.png': 'image/png',
    '.svg': 'image/svg+xml',
  }[extension] ?? 'application/octet-stream';
}

async function startLocalServer(rootDirectory) {
  const root = path.resolve(rootDirectory);
  const server = createServer(async (request, response) => {
    try {
      const requestUrl = new URL(request.url ?? '/', 'http://127.0.0.1');
      const relativeRequestPath = decodeURIComponent(requestUrl.pathname).replace(/^\/+/, '');
      if (relativeRequestPath === 'favicon.ico') {
        response.writeHead(204).end();
        return;
      }
      const filePath = path.resolve(root, relativeRequestPath);
      const relativeFilePath = path.relative(root, filePath);
      if (
        relativeFilePath.startsWith(`..${path.sep}`) ||
        relativeFilePath === '..' ||
        path.isAbsolute(relativeFilePath)
      ) {
        response.writeHead(403).end('Forbidden');
        return;
      }

      const details = await stat(filePath);
      if (!details.isFile()) {
        response.writeHead(404).end('Not Found');
        return;
      }
      response.writeHead(200, {
        'Content-Type': contentType(filePath),
        'Content-Length': details.size,
        'Cache-Control': 'no-store',
      });
      if (request.method === 'HEAD') response.end();
      else {
        const stream = createReadStream(filePath);
        stream.on('error', () => response.destroy());
        stream.pipe(response);
      }
    } catch (error) {
      response.writeHead(404).end('Not Found');
    }
  });

  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  const address = server.address();
  check(address && typeof address !== 'string', 'local HTTP server did not expose a port');
  return {
    server,
    origin: `http://127.0.0.1:${address.port}`,
  };
}

async function closeServer(server) {
  if (!server) return;
  await new Promise((resolve, reject) => {
    server.close((error) => (error ? reject(error) : resolve()));
  });
}

async function pageMeasurements(page) {
  return page.locator('[data-resume-editor]').evaluate((editor) => {
    const style = getComputedStyle(editor);
    return {
      clientHeight: editor.clientHeight,
      scrollHeight: editor.scrollHeight,
      widthPixels: Number.parseFloat(style.width),
      heightPixels: Number.parseFloat(style.height),
    };
  });
}

async function contentBoundaryViolations(page) {
  return page.locator('[data-resume-editor]').evaluate((editor) => {
    const pageBounds = editor.getBoundingClientRect();
    const tolerance = 1.5;
    const clippingOverflow = new Set(['hidden', 'clip', 'scroll', 'auto']);
    const mechanicsSelector = [
      '.block-drag-handle',
      '.block-resize-handle',
      '.block-drop-indicator',
    ].join(', ');
    const describe = (element) => {
      if (element.id) return `${element.tagName.toLowerCase()}#${element.id}`;
      if (element.dataset.blockId) {
        return `${element.tagName.toLowerCase()}[data-block-id="${element.dataset.blockId}"]`;
      }
      if (element.classList.length) {
        return `${element.tagName.toLowerCase()}.${Array.from(element.classList).join('.')}`;
      }
      return element.tagName.toLowerCase();
    };
    const isRendered = (element) => {
      const style = getComputedStyle(element);
      return element.getClientRects().length > 0 &&
        style.display !== 'none' &&
        style.visibility !== 'hidden' &&
        style.visibility !== 'collapse' &&
        style.opacity !== '0';
    };
    const isMechanic = (element) => Boolean(element.closest(mechanicsSelector));
    const outside = (bounds) => (
      bounds.left < pageBounds.left - tolerance ||
      bounds.right > pageBounds.right + tolerance ||
      bounds.top < pageBounds.top - tolerance ||
      bounds.bottom > pageBounds.bottom + tolerance
    );
    const violations = new Set();
    const checkClippingAncestors = (element, bounds, contentLabel) => {
      for (
        let ancestor = element;
        ancestor && editor.contains(ancestor);
        ancestor = ancestor.parentElement
      ) {
        if (!isRendered(ancestor) || isMechanic(ancestor)) continue;
        const style = getComputedStyle(ancestor);
        const ancestorBounds = ancestor.getBoundingClientRect();
        const clippedHorizontally = clippingOverflow.has(style.overflowX) &&
          (bounds.left < ancestorBounds.left - tolerance ||
            bounds.right > ancestorBounds.right + tolerance);
        const clippedVertically = clippingOverflow.has(style.overflowY) &&
          (bounds.top < ancestorBounds.top - tolerance ||
            bounds.bottom > ancestorBounds.bottom + tolerance);
        if (clippedHorizontally || clippedVertically) {
          violations.add(
            `${contentLabel} clipped by ${describe(ancestor)} ` +
            `(overflow ${style.overflowX}/${style.overflowY}; ` +
            `scroll ${ancestor.scrollWidth}x${ancestor.scrollHeight}; ` +
            `client ${ancestor.clientWidth}x${ancestor.clientHeight})`
          );
        }
      }
    };

    for (const element of [editor, ...editor.querySelectorAll('*')]) {
      if (!isRendered(element) || isMechanic(element)) continue;
      const style = getComputedStyle(element);
      if (
        clippingOverflow.has(style.overflowX) &&
        element.scrollWidth > element.clientWidth + tolerance
      ) {
        violations.add(
          `${describe(element)} clips horizontal content ` +
          `(overflow-x ${style.overflowX}; scrollWidth ${element.scrollWidth}; ` +
          `clientWidth ${element.clientWidth})`
        );
      }
      if (
        clippingOverflow.has(style.overflowY) &&
        element.scrollHeight > element.clientHeight + tolerance
      ) {
        violations.add(
          `${describe(element)} clips vertical content ` +
          `(overflow-y ${style.overflowY}; scrollHeight ${element.scrollHeight}; ` +
          `clientHeight ${element.clientHeight})`
        );
      }
    }

    const walker = document.createTreeWalker(editor, NodeFilter.SHOW_TEXT);
    let node = walker.nextNode();
    while (node) {
      const parent = node.parentElement;
      if (node.textContent.trim() && parent && isRendered(parent) && !isMechanic(parent)) {
        const range = document.createRange();
        range.selectNodeContents(node);
        for (const bounds of range.getClientRects()) {
          if (bounds.width && bounds.height && outside(bounds)) {
            violations.add(`text outside A4: ${node.textContent.trim().slice(0, 40)}`);
          }
          if (bounds.width && bounds.height) {
            checkClippingAncestors(
              parent,
              bounds,
              `text "${node.textContent.trim().slice(0, 40)}"`
            );
          }
        }
      }
      node = walker.nextNode();
    }
    for (const element of editor.querySelectorAll('img, svg, canvas, video')) {
      if (!isRendered(element) || isMechanic(element)) continue;
      const bounds = element.getBoundingClientRect();
      if (!bounds.width || !bounds.height) continue;
      if (outside(bounds)) {
        violations.add(`${describe(element)} outside A4`);
      }
      checkClippingAncestors(element, bounds, describe(element));
    }
    return Array.from(violations);
  });
}

async function assertPageIntegrity(page, label) {
  const measurements = await pageMeasurements(page);
  const widthMm = measurements.widthPixels / PX_PER_MM;
  const heightMm = measurements.heightPixels / PX_PER_MM;
  check(
    Math.abs(widthMm - A4_WIDTH_MM) <= MM_TOLERANCE,
    `${label}: page width is ${widthMm.toFixed(2)} mm; expected 210 ± 0.6 mm`
  );
  check(
    Math.abs(heightMm - A4_HEIGHT_MM) <= MM_TOLERANCE,
    `${label}: page height is ${heightMm.toFixed(2)} mm; expected 297 ± 0.6 mm`
  );
  check(
    measurements.scrollHeight <= measurements.clientHeight + PAGE_OVERFLOW_TOLERANCE,
    `${label}: content overflows A4 (${measurements.scrollHeight}px scrollHeight, ` +
      `${measurements.clientHeight}px clientHeight)`
  );
  const violations = await contentBoundaryViolations(page);
  check(
    violations.length === 0,
    `${label}: content boundary/clipping violations: ${violations.join('; ')}`
  );
  return { ...measurements, widthMm, heightMm };
}

async function directBlockIds(group) {
  return group.locator(':scope > .editable-block').evaluateAll((blocks) =>
    blocks.map((block) => block.dataset.blockId)
  );
}

async function selectSortableGroup(page, excludedIndexes = new Set()) {
  const groups = page.locator('[data-resume-editor] [data-sortable-group]');
  let fallback;
  for (let index = 0; index < await groups.count(); index += 1) {
    const group = groups.nth(index);
    const order = await directBlockIds(group);
    if (order.length < 2) continue;
    const selection = {
      group,
      index,
      name: await group.getAttribute('data-sortable-group'),
      order,
    };
    if (!fallback) fallback = selection;
    if (!excludedIndexes.has(index)) return selection;
  }
  check(fallback, 'reorder interaction needs a sortable group with two direct editable blocks');
  return fallback;
}

function swapAdjacent(values, firstIndex = 0) {
  check(
    firstIndex >= 0 && firstIndex + 1 < values.length,
    `cannot swap adjacent blocks at index ${firstIndex} in ${values.join(', ')}`
  );
  const swapped = [...values];
  [swapped[firstIndex], swapped[firstIndex + 1]] = [
    swapped[firstIndex + 1],
    swapped[firstIndex],
  ];
  return swapped;
}

function blockById(page, blockId) {
  return page.locator(`[data-block-id=${JSON.stringify(blockId)}]`);
}

async function groupContainsBlock(group, blockId) {
  return group.evaluate(
    (element, expectedId) => Array.from(element.children).some(
      (child) => child.classList.contains('editable-block') &&
        child.dataset.blockId === expectedId
    ),
    blockId
  );
}

function equalArrays(left, right) {
  return left.length === right.length && left.every((value, index) => value === right[index]);
}

async function dragPointer(page, source, target, targetPlacement = 'after') {
  await source.hover();
  const sourceBounds = await source.boundingBox();
  check(sourceBounds, 'pointer drag source has no rendered bounds');
  const sourceX = sourceBounds.x + sourceBounds.width / 2;
  const sourceY = sourceBounds.y + sourceBounds.height / 2;
  await page.mouse.move(sourceX, sourceY);
  await page.mouse.down();
  const targetBounds = await target.boundingBox();
  check(targetBounds, 'pointer drag target has no rendered bounds');
  const targetX = targetBounds.x + Math.min(targetBounds.width / 2, 40);
  const targetY = targetPlacement === 'after'
    ? targetBounds.y + targetBounds.height - 2
    : targetBounds.y + 2;
  await page.mouse.move(targetX, targetY, { steps: 8 });
  await page.mouse.up();
}

async function resizeBlock(page, block, deltaY) {
  const before = await block.boundingBox();
  const handle = block.locator(':scope > .block-resize-handle');
  await handle.hover();
  const bounds = await handle.boundingBox();
  check(before && bounds, 'resize handle has no rendered bounds');
  const x = bounds.x + bounds.width / 2;
  const y = bounds.y + bounds.height / 2;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x, y + deltaY, { steps: 6 });
  await page.mouse.up();
  const after = await block.boundingBox();
  const minHeight = await block.evaluate((element) => element.style.minHeight);
  check(after, 'resized block has no rendered bounds');
  check(
    after.height > before.height + Math.max(2, deltaY - 6),
    `vertical resize did not change visual height (${before.height}px to ${after.height}px)`
  );
  check(minHeight.endsWith('px'), `vertical resize did not store a pixel height: ${minHeight}`);
  return minHeight;
}

const FICTIONAL_SVG = Buffer.from(
  '<svg xmlns="http://www.w3.org/2000/svg" width="300" height="400" viewBox="0 0 300 400">' +
    '<rect width="300" height="400" fill="#e6edf8"/>' +
    '<circle cx="150" cy="126" r="66" fill="#8294b8"/>' +
    '<path d="M45 390c8-105 56-157 105-157s97 52 105 157" fill="#405273"/>' +
  '</svg>',
  'utf8'
);

async function uploadFictionalPhoto(page) {
  await page.locator('#photoInput').setInputFiles({
    name: 'fictional-portrait.svg',
    mimeType: 'image/svg+xml',
    buffer: FICTIONAL_SVG,
  });
  await page.waitForFunction(() => {
    const image = document.querySelector('.photo-image');
    return image &&
      !image.hidden &&
      image.src.startsWith('data:image/jpeg') &&
      image.complete &&
      image.naturalWidth > 0 &&
      image.naturalHeight > 0;
  });
  const result = await page.evaluate(() => {
    const uploader = document.querySelector('[data-photo-uploader]');
    const image = uploader.querySelector('.photo-image');
    const area = uploader.getBoundingClientRect();
    const picture = image.getBoundingClientRect();
    return {
      source: image.src.slice(0, 23),
      hidden: image.hidden,
      contained:
        picture.left >= area.left - 1 && picture.right <= area.right + 1 &&
        picture.top >= area.top - 1 && picture.bottom <= area.bottom + 1,
      renderedWidth: picture.width,
      renderedHeight: picture.height,
      complete: image.complete,
      naturalWidth: image.naturalWidth,
      naturalHeight: image.naturalHeight,
      areaBounds: {
        left: area.left,
        top: area.top,
        right: area.right,
        bottom: area.bottom,
      },
      pictureBounds: {
        left: picture.left,
        top: picture.top,
        right: picture.right,
        bottom: picture.bottom,
      },
    };
  });
  check(result.source.startsWith('data:image/jpeg;base64,'), 'photo was not converted to JPEG');
  check(
    !result.hidden &&
      result.complete &&
      result.naturalWidth > 0 &&
      result.naturalHeight > 0 &&
      result.renderedWidth > 0 &&
      result.renderedHeight > 0,
    `photo is not fully decoded/rendered (complete=${result.complete}; ` +
      `natural=${result.naturalWidth}x${result.naturalHeight}; ` +
      `rendered=${result.renderedWidth}x${result.renderedHeight})`
  );
  check(
    result.contained,
    `photo extends outside the portrait area: ${JSON.stringify({
      area: result.areaBounds,
      picture: result.pictureBounds,
    })}`
  );
}

async function removePhoto(page) {
  await page.locator('[data-photo-action="remove"]').click();
  const state = await page.evaluate(() => {
    const image = document.querySelector('.photo-image');
    const emptyState = document.querySelector('.photo-empty-state');
    return {
      imageHidden: image.hidden,
      imageHasSource: image.hasAttribute('src'),
      emptyHidden: emptyState.hidden,
    };
  });
  check(state.imageHidden && !state.imageHasSource, 'remove photo did not clear the portrait image');
  check(!state.emptyHidden, 'remove photo did not restore the empty portrait state');
}

async function waitForSavedDraft(page) {
  await page.waitForFunction(() => document.getElementById('saveStatus')?.textContent === '已保存');
  return page.evaluate(() => {
    const keys = Object.keys(localStorage).filter((key) => key.startsWith('resume-editor:'));
    return {
      keys,
      values: keys.map((key) => localStorage.getItem(key)),
    };
  });
}

function windowsSlug(value) {
  return value
    .trim()
    .replace(/[\s<>:"/\\|?*'“”‘’_-]+/gu, '-')
    .replace(/^[ .-]+|[ .-]+$/gu, '');
}

async function expectedStorageKey(page) {
  const target = await page.evaluate(() => {
    const role = document.querySelector('.job-panel h1')?.textContent.trim() ?? '';
    const title = document.title;
    const suffix = `｜${role}｜岗位定制简历`;
    return {
      role,
      company: title.endsWith(suffix) ? title.slice(0, -suffix.length) : '',
    };
  });
  const company = windowsSlug(target.company);
  const role = windowsSlug(target.role);
  check(company && role, 'page contract did not expose nonempty company and role storage components');
  return `resume-editor:${company}:${role}:v1`;
}

async function assertPrintHidden(page, selector, label, required = true) {
  const state = await page.locator(selector).evaluateAll((elements) => ({
    count: elements.length,
    rendered: elements.filter((element) => element.getClientRects().length > 0).length,
  }));
  if (required) check(state.count > 0, `print check could not locate ${label}`);
  check(state.rendered === 0, `print check found ${state.rendered} rendered ${label} element(s)`);
}

async function assertPrintControlsHidden(page) {
  for (const { selector, label, required } of [
    { selector: '.job-panel', label: 'left target panel', required: true },
    { selector: '.app-toolbar', label: 'toolbar/editor controls', required: true },
    { selector: '.review-badge', label: 'review badge', required: false },
    { selector: '.review-note', label: 'review note', required: false },
    { selector: '[data-missing-info="phone"]', label: 'missing phone prompt', required: false },
    { selector: '[data-missing-info="email"]', label: 'missing email prompt', required: false },
    { selector: '.photo-empty-state', label: 'missing photo prompt', required: true },
    { selector: '.block-drag-handle', label: 'drag handles', required: true },
    { selector: '.block-resize-handle', label: 'resize handles', required: true },
  ]) {
    await assertPrintHidden(page, selector, label, required);
  }
}

async function exerciseExportConfirmation(page) {
  const printButton = page.locator('#printBtn');
  const unresolvedCount = Number(await printButton.getAttribute('data-unresolved-count'));
  check(
    Number.isInteger(unresolvedCount) && unresolvedCount >= 0,
    `export button has invalid unresolved count: ${unresolvedCount}`
  );
  await page.evaluate(() => {
    window.__qaPrintCalls = 0;
    window.print = () => { window.__qaPrintCalls += 1; };
  });
  const printCalls = () => page.evaluate(() => window.__qaPrintCalls);

  if (unresolvedCount === 0) {
    let unexpectedDialog = '';
    const dismissUnexpectedDialog = async (dialog) => {
      unexpectedDialog = dialog.message();
      await dialog.dismiss();
    };
    page.on('dialog', dismissUnexpectedDialog);
    try {
      await printButton.click();
      await page.waitForTimeout(50);
    } finally {
      page.off('dialog', dismissUnexpectedDialog);
    }
    check(!unexpectedDialog, `resolved export opened a confirmation: ${unexpectedDialog}`);
    check(await printCalls() === 1, 'resolved export did not call print directly');
    return;
  }

  let cancelMessage = '';
  page.once('dialog', async (dialog) => {
    cancelMessage = dialog.message();
    await dialog.dismiss();
  });
  await printButton.click();
  check(
    cancelMessage.includes(`${unresolvedCount} 项待核实内容`) &&
      cancelMessage.includes('是否继续导出'),
    `unresolved export confirmation is unclear: ${cancelMessage}`
  );
  check(await printCalls() === 0, 'cancelled unresolved export still called print');

  let confirmMessage = '';
  page.once('dialog', async (dialog) => {
    confirmMessage = dialog.message();
    await dialog.accept();
  });
  await printButton.click();
  check(confirmMessage === cancelMessage, 'confirm and cancel export messages differ');
  check(await printCalls() === 1, 'confirmed unresolved export did not call print');
}

async function prepareForPdfCapture(page, label) {
  const focusState = await page.evaluate(() => {
    const active = document.activeElement;
    if (active instanceof HTMLElement) active.blur();
    const selection = window.getSelection();
    selection?.removeAllRanges();
    document.body.tabIndex = -1;
    document.body.focus({ preventScroll: true });
    document.body.removeAttribute('tabindex');
    const captureTarget = document.activeElement;
    return {
      activeElement: captureTarget?.tagName.toLowerCase() ?? 'none',
      activeIsContentEditable: Boolean(captureTarget?.isContentEditable),
      selectionRangeCount: window.getSelection()?.rangeCount ?? 0,
    };
  });
  check(
    !focusState.activeIsContentEditable,
    `${label}: active element ${focusState.activeElement} remains contenteditable`
  );
  check(
    focusState.selectionRangeCount === 0,
    `${label}: selection still has ${focusState.selectionRangeCount} range(s)`
  );

  const caretState = await page.locator('[data-resume-editor]').evaluate((editor) => {
    const elements = [
      editor,
      editor.querySelector('.resume-name'),
      editor.querySelector('.block-content'),
    ].filter(Boolean);
    return elements.map((element) => ({
      description: element.className || element.tagName.toLowerCase(),
      isContentEditable: element.isContentEditable,
      caretColor: getComputedStyle(element).caretColor,
    }));
  });
  check(caretState.length === 3, `${label}: could not locate representative editable content`);
  const visibleCarets = caretState.filter(
    (state) => !['transparent', 'rgba(0, 0, 0, 0)'].includes(state.caretColor)
  );
  check(
    caretState.every((state) => state.isContentEditable),
    `${label}: representative resume content is not contenteditable: ` +
      caretState.map((state) => state.description).join(', ')
  );
  check(
    visibleCarets.length === 0,
    `${label}: print caret color is visible: ` +
      visibleCarets.map((state) => `${state.description}=${state.caretColor}`).join(', ')
  );
}

async function assertEmptyPrintPortrait(page) {
  const state = await page.evaluate(() => {
    const area = document.querySelector('[data-photo-uploader]');
    const image = area.querySelector('.photo-image');
    const bounds = area.getBoundingClientRect();
    const style = getComputedStyle(area);
    return {
      width: bounds.width,
      height: bounds.height,
      background: style.backgroundColor,
      imageRendered: image.getClientRects().length > 0,
      imageHasSource: image.hasAttribute('src'),
    };
  });
  check(state.width > 90 && state.height > 120, 'empty print portrait area lost its reserved size');
  check(state.background === 'rgb(255, 255, 255)', `empty print portrait is not white: ${state.background}`);
  check(!state.imageRendered && !state.imageHasSource, 'empty print portrait unexpectedly renders an image');
}

async function assertPhotoPrintPortrait(page) {
  const state = await page.evaluate(() => {
    const area = document.querySelector('[data-photo-uploader]').getBoundingClientRect();
    const imageElement = document.querySelector('.photo-image');
    const image = imageElement.getBoundingClientRect();
    return {
      source: imageElement.src.slice(0, 23),
      rendered: imageElement.getClientRects().length > 0,
      contained:
        image.left >= area.left - 1 && image.right <= area.right + 1 &&
        image.top >= area.top - 1 && image.bottom <= area.bottom + 1,
    };
  });
  check(state.source.startsWith('data:image/jpeg;base64,'), 'print portrait is not a JPEG data URL');
  check(state.rendered && state.contained, 'print portrait is hidden or outside its reserved area');
}

async function inspectPdf(pdfinfoPath, pdfPath) {
  let stdout;
  try {
    ({ stdout } = await execFileAsync(pdfinfoPath, [pdfPath], {
      encoding: 'utf8',
      windowsHide: true,
    }));
  } catch (error) {
    fail(`pdfinfo failed for ${pdfPath}: ${error.stderr || error.message}`);
  }
  const pagesMatch = stdout.match(/^Pages:\s+(\d+)\s*$/m);
  const sizeMatch = stdout.match(/^Page size:\s+([\d.]+) x ([\d.]+) pts(?:\s+\(A4\))?\s*$/m);
  check(pagesMatch, `pdfinfo did not report Pages for ${pdfPath}`);
  check(sizeMatch, `pdfinfo did not report parseable Page size for ${pdfPath}`);
  const pages = Number(pagesMatch[1]);
  const widthPoints = Number(sizeMatch[1]);
  const heightPoints = Number(sizeMatch[2]);
  check(pages === 1, `${path.basename(pdfPath)} has ${pages} pages; expected exactly 1`);
  check(
    Math.abs(widthPoints - 595.28) <= 1 && Math.abs(heightPoints - 841.89) <= 1,
    `${path.basename(pdfPath)} is ${widthPoints} x ${heightPoints} pt; expected A4`
  );
  return { pages, widthPoints, heightPoints };
}

async function exerciseEditor(page) {
  const editor = page.locator('[data-resume-editor]');
  await editor.waitFor({ state: 'visible' });
  await exerciseExportConfirmation(page);
  const initialHtml = await editor.evaluate((element) => element.innerHTML);
  const keyboardGroup = await selectSortableGroup(page);
  const resetStates = new Map([
    [keyboardGroup.index, { group: keyboardGroup, expected: keyboardGroup.order }],
  ]);
  const persistedStates = new Map();

  const editedBlockId = keyboardGroup.order[0];
  const editField = blockById(page, editedBlockId).locator(':scope > .block-content');
  const originalText = (await editField.textContent()).trim();
  await editField.click();
  await page.keyboard.press('End');
  await page.keyboard.insertText(' [QA edit]');
  await page.waitForTimeout(400);
  const editedText = (await editField.textContent()).trim();
  check(editedText === `${originalText} [QA edit]`, 'direct contenteditable edit was not applied');

  await page.locator('#undoBtn').click();
  check((await editField.textContent()).trim() === originalText, 'undo did not restore edited text');
  await page.locator('#redoBtn').click();
  check((await editField.textContent()).trim() === editedText, 'redo did not restore edited text');
  await assertPageIntegrity(page, 'after edit/undo/redo interaction');

  const keyboardBlock = blockById(page, editedBlockId);
  const keyboardHandle = keyboardBlock.locator(':scope > .block-drag-handle');
  await keyboardHandle.press('Alt+ArrowDown');
  const keyboardOrder = await directBlockIds(keyboardGroup.group);
  const expectedKeyboardOrder = swapAdjacent(keyboardGroup.order);
  check(
    equalArrays(keyboardOrder, expectedKeyboardOrder),
    `Alt+ArrowDown in ${keyboardGroup.name} produced ${keyboardOrder.join(', ')}; ` +
      `expected ${expectedKeyboardOrder.join(', ')}`
  );
  check(
    await groupContainsBlock(keyboardGroup.group, editedBlockId),
    'keyboard reorder moved a block outside its sortable group'
  );
  persistedStates.set(keyboardGroup.index, {
    group: keyboardGroup,
    expected: expectedKeyboardOrder,
  });
  await assertPageIntegrity(page, 'after keyboard reorder interaction');

  const pointerGroup = await selectSortableGroup(page, new Set([keyboardGroup.index]));
  const pointerInitialOrder = await directBlockIds(pointerGroup.group);
  if (!resetStates.has(pointerGroup.index)) {
    resetStates.set(pointerGroup.index, {
      group: pointerGroup,
      expected: pointerInitialOrder,
    });
  }
  const pointerSourceId = pointerInitialOrder[0];
  const pointerTargetId = pointerInitialOrder[1];
  const pointerBlock = blockById(page, pointerSourceId);
  const pointerTarget = blockById(page, pointerTargetId).locator(':scope > .block-content');
  await dragPointer(
    page,
    pointerBlock.locator(':scope > .block-drag-handle'),
    pointerTarget,
    'after'
  );
  const pointerOrder = await directBlockIds(pointerGroup.group);
  const expectedPointerOrder = swapAdjacent(pointerInitialOrder);
  check(
    equalArrays(pointerOrder, expectedPointerOrder),
    `pointer drag in ${pointerGroup.name} produced ${pointerOrder.join(', ')}; ` +
      `expected ${expectedPointerOrder.join(', ')}`
  );
  check(
    await groupContainsBlock(pointerGroup.group, pointerSourceId),
    'pointer drag moved a block outside its sortable group'
  );
  persistedStates.set(pointerGroup.index, {
    group: pointerGroup,
    expected: expectedPointerOrder,
  });
  await assertPageIntegrity(page, 'after pointer drag interaction');

  const resizeBlockTarget = blockById(page, pointerTargetId);
  const baselineBounds = await resizeBlockTarget.boundingBox();
  check(baselineBounds, 'resize target has no baseline bounds');
  const baselineHeight = baselineBounds.height;
  await resizeBlock(page, resizeBlockTarget, 18);
  const resizeHandle = resizeBlockTarget.locator(':scope > .block-resize-handle');
  await resizeHandle.dblclick();
  check(
    (await resizeBlockTarget.evaluate((element) => element.style.minHeight)) === '',
    'double-click did not reset the custom block height'
  );
  const resetBounds = await resizeBlockTarget.boundingBox();
  check(resetBounds, 'resize target has no bounds after double-click reset');
  check(
    Math.abs(resetBounds.height - baselineHeight) <= 1,
    `double-click reset visual height to ${resetBounds.height}px; ` +
      `expected baseline ${baselineHeight}px`
  );
  const persistedMinHeight = await resizeBlock(page, resizeBlockTarget, 14);
  await assertPageIntegrity(page, 'after resize/reset interaction');

  await uploadFictionalPhoto(page);
  await assertPageIntegrity(page, 'after fictional photo upload interaction');
  await removePhoto(page);
  await assertPageIntegrity(page, 'after photo removal interaction');

  const draft = await waitForSavedDraft(page);
  const expectedKey = await expectedStorageKey(page);
  check(draft.keys.length === 1, `expected one job-specific draft key, found: ${draft.keys.join(', ')}`);
  const keyStructure = draft.keys[0].match(/^resume-editor:([^:]+):([^:]+):v1$/u);
  check(
    keyStructure && keyStructure[1].trim() && keyStructure[2].trim(),
    `draft key lacks nonempty company/role v1 components: ${draft.keys[0]}`
  );
  check(
    draft.keys[0] === expectedKey,
    `draft key ${draft.keys[0]} does not match page contract ${expectedKey}`
  );
  check(draft.values[0], 'job-specific v1 draft is empty');

  await page.reload({ waitUntil: 'load' });
  await page.locator('[data-resume-editor]').waitFor({ state: 'visible' });
  check(
    (await blockById(page, editedBlockId).locator(':scope > .block-content').textContent()).trim() === editedText,
    'autosave did not persist the edited text after reload'
  );
  for (const { group, expected } of persistedStates.values()) {
    const actual = await directBlockIds(group.group);
    check(
      equalArrays(actual, expected),
      `autosave did not persist ${group.name} order: ${actual.join(', ')}`
    );
  }
  check(
    await blockById(page, pointerTargetId).evaluate(
      (element, expected) => element.style.minHeight === expected,
      persistedMinHeight
    ),
    'autosave did not persist the resized block height after reload'
  );
  await assertPageIntegrity(page, 'after autosaved state reload');

  page.once('dialog', (dialog) => dialog.accept());
  await page.locator('#resetBtn').click();
  check(
    (await editor.evaluate((element) => element.innerHTML)) === initialHtml,
    'reset did not restore the original rendered content and spacing'
  );
  for (const { group, expected } of resetStates.values()) {
    const actual = await directBlockIds(group.group);
    check(
      equalArrays(actual, expected),
      `reset did not restore ${group.name} order: ${actual.join(', ')}`
    );
  }
  const remainingKeys = await page.evaluate(() =>
    Object.keys(localStorage).filter((key) => key.startsWith('resume-editor:'))
  );
  check(remainingKeys.length === 0, `reset did not clear saved state: ${remainingKeys.join(', ')}`);
  await assertPageIntegrity(page, 'after clean reset interaction');
}

async function createAndInspectPdfs(page, options) {
  const emptyPdfPath = path.join(options.outDir, EMPTY_PDF_NAME);
  const photoPdfPath = path.join(options.outDir, PHOTO_PDF_NAME);
  const pdfOptions = {
    format: 'A4',
    printBackground: true,
    preferCSSPageSize: true,
    displayHeaderFooter: false,
  };

  await page.emulateMedia({ media: 'print' });
  await assertPrintControlsHidden(page);
  await assertEmptyPrintPortrait(page);
  const layout = await assertPageIntegrity(page, 'before empty-photo PDF');
  await prepareForPdfCapture(page, 'before empty-photo PDF');
  await page.pdf({ ...pdfOptions, path: emptyPdfPath });
  const emptyInfo = await inspectPdf(options.pdfinfo, emptyPdfPath);

  await uploadFictionalPhoto(page);
  await assertPrintControlsHidden(page);
  await assertPhotoPrintPortrait(page);
  await assertPageIntegrity(page, 'before fictional-photo PDF');
  await prepareForPdfCapture(page, 'before fictional-photo PDF');
  await page.pdf({ ...pdfOptions, path: photoPdfPath });
  const photoInfo = await inspectPdf(options.pdfinfo, photoPdfPath);

  return { layout, emptyPdfPath, photoPdfPath, emptyInfo, photoInfo };
}

function isAllowedNetworkUrl(requestUrl, localOrigin, webSocket = false) {
  try {
    const parsed = new URL(requestUrl);
    const local = new URL(localOrigin);
    if (['data:', 'blob:', 'about:'].includes(parsed.protocol)) return true;
    if (parsed.origin === local.origin) return true;
    return webSocket &&
      ['ws:', 'wss:'].includes(parsed.protocol) &&
      parsed.hostname === local.hostname &&
      parsed.port === local.port;
  } catch (error) {
    return false;
  }
}

async function main() {
  const options = parseArguments(process.argv.slice(2));
  await validatePath(options.html, 'file', 'HTML path');
  await validatePath(options.outDir, 'directory', 'output directory');
  await validatePath(options.browserExecutable, 'file', 'browser executable');
  await validatePath(options.pdfinfo, 'file', 'pdfinfo executable');

  let server;
  let browser;
  let context;
  let page;
  let result;
  let validationError;
  const browserErrors = [];
  const networkAttempts = [];
  try {
    const local = await startLocalServer(path.dirname(options.html));
    server = local.server;
    const pageUrl = `${local.origin}/${encodeURIComponent(path.basename(options.html))}`;
    browser = await chromium.launch({
      executablePath: options.browserExecutable,
      headless: true,
    });
    context = await browser.newContext({
      viewport: VIEWPORT,
      serviceWorkers: 'block',
    });
    await context.route('**/*', async (route) => {
      const requestUrl = route.request().url();
      if (isAllowedNetworkUrl(requestUrl, local.origin)) await route.continue();
      else {
        networkAttempts.push(requestUrl);
        await route.abort('blockedbyclient');
      }
    });
    check(
      typeof context.routeWebSocket === 'function',
      'installed Playwright does not support context-wide WebSocket routing'
    );
    await context.routeWebSocket(/.*/, async (webSocket) => {
      const requestUrl = webSocket.url();
      if (isAllowedNetworkUrl(requestUrl, local.origin, true)) {
        webSocket.connectToServer();
      } else {
        networkAttempts.push(requestUrl);
        await webSocket.close({ code: 1008, reason: 'External network blocked' });
      }
    });
    const instrumentedPages = new WeakSet();
    const collectPageDiagnostics = (candidatePage) => {
      if (instrumentedPages.has(candidatePage)) return;
      instrumentedPages.add(candidatePage);
      candidatePage.on(
        'pageerror',
        (error) => browserErrors.push(`page error: ${error.message}`)
      );
      candidatePage.on('console', (message) => {
        if (message.type() === 'error') {
          const location = message.location();
          const source = location.url ? ` (${location.url}:${location.lineNumber})` : '';
          browserErrors.push(`console.error: ${message.text()}${source}`);
        }
      });
    };
    context.on('page', collectPageDiagnostics);
    page = await context.newPage();
    collectPageDiagnostics(page);
    const response = await page.goto(pageUrl, { waitUntil: 'load' });
    check(response?.ok(), `resume request failed with HTTP ${response?.status() ?? 'unknown'}`);

    await assertPageIntegrity(page, 'initial browser layout');
    await exerciseEditor(page);
    result = await createAndInspectPdfs(page, options);
    await page.waitForTimeout(400);
  } catch (error) {
    validationError = error;
  }

  const cleanupErrors = [];
  for (const [label, close] of [
    ['page', () => page?.close()],
    ['context', () => context?.close()],
    ['browser', () => browser?.close()],
    ['server', () => closeServer(server)],
  ]) {
    try {
      await close();
    } catch (error) {
      cleanupErrors.push(`${label}: ${error.message}`);
    }
  }
  const failureDiagnostics = [];
  if (validationError) failureDiagnostics.push(validationError.message);
  if (networkAttempts.length) {
    failureDiagnostics.push(
      `blocked external network attempts:\n` +
        networkAttempts.map((url) => `- ${url}`).join('\n')
    );
  }
  if (browserErrors.length) {
    failureDiagnostics.push(
      `browser emitted errors:\n${browserErrors.map((error) => `- ${error}`).join('\n')}`
    );
  }
  if (cleanupErrors.length) {
    failureDiagnostics.push(`cleanup failed: ${cleanupErrors.join('; ')}`);
  }
  if (failureDiagnostics.length) {
    fail(failureDiagnostics.join('\n'));
  }

  process.stdout.write(
    `PASS: browser interactions; A4 ${result.layout.widthMm.toFixed(2)} x ` +
    `${result.layout.heightMm.toFixed(2)} mm; scrollHeight/clientHeight ` +
    `${result.layout.scrollHeight}/${result.layout.clientHeight}px; ` +
    `${browserErrors.length} browser errors; ${networkAttempts.length} external network attempts; ` +
    `${path.basename(result.emptyPdfPath)} and ${path.basename(result.photoPdfPath)} ` +
    `are one-page A4 PDFs\n`
  );
}

main().catch((error) => {
  process.stderr.write(`VALIDATION FAILED: ${error.message}\n`);
  process.exitCode = 1;
});

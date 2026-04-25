// Minimal local webhook sink used only by the Phase 5 smoke test.
// Logs every POST body as a single JSON line for easy grep / assertion.
import http from 'node:http';

const port = Number(process.env.PORT ?? 7788);
http
  .createServer((req, res) => {
    let body = '';
    req.on('data', (chunk) => {
      body += chunk;
    });
    req.on('end', () => {
      try {
        const parsed = JSON.parse(body || '{}');
        const title = parsed?.card?.header?.title?.content ?? '(no title)';
        const template = parsed?.card?.header?.template ?? '(no template)';
        console.log(
          JSON.stringify({ t: new Date().toISOString(), title, template }),
        );
      } catch (err) {
        console.log(
          JSON.stringify({ t: new Date().toISOString(), err: String(err), raw: body }),
        );
      }
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end('{"ok":true}');
    });
  })
  .listen(port, () => {
    console.log(`[lark-sink] listening on :${port}`);
  });

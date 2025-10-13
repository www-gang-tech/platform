# Live Reload Demo

## What is Live Reload?

Live reload automatically refreshes your browser when you make changes to your content, templates, or public assets. This makes development much faster and more enjoyable!

## How to Use

### 1. Start the Dev Server

```bash
cd /Users/danielhirunrusme/Documents/gang-platform
gang serve
```

You'll see:
```
🚀 Starting dev server with live reload...
🔨 Initial build...
✅ Build complete!
👀 Watching: /path/to/content
👀 Watching: /path/to/templates
👀 Watching: /path/to/public

✅ Dev server running at http://127.0.0.1:8000
📝 Live reload enabled - changes will auto-refresh the browser
Press Ctrl+C to stop
```

### 2. Open Your Browser

Navigate to http://localhost:8000 in your browser.

### 3. Make Changes

Try editing any file:
- **Content**: Edit `content/posts/qi2-launch.md`
- **Templates**: Modify `templates/base.html`
- **Assets**: Update files in `public/`

### 4. Watch the Magic

When you save a file:
1. The CLI detects the change and shows: `📝 Change detected: filename.md`
2. The site rebuilds automatically: `🔨 Rebuilding site...`
3. Your browser refreshes automatically to show the changes!

## Features

✅ **File Watching** - Monitors content, templates, and public directories  
✅ **Auto Rebuild** - Rebuilds site on any change  
✅ **Browser Refresh** - Auto-refreshes all open browser tabs  
✅ **Debouncing** - Prevents multiple rebuilds for rapid changes  
✅ **Error Handling** - Shows build errors without crashing  
✅ **Clean Output** - Suppresses noisy HTTP logs  

## Custom Port

Use a different port:
```bash
gang serve --port 3000 --host 0.0.0.0
```

## Technical Details

The live reload system uses:
- **Watchdog**: For efficient file system monitoring
- **Server-Sent Events (SSE)**: For pushing reload notifications to the browser
- **HTTP Server**: Built-in Python HTTP server with custom handlers
- **Script Injection**: Automatically injects reload client into HTML pages

## Troubleshooting

### Port Already in Use

```bash
gang serve --port 8001
```

### Watchdog Not Installed

```bash
pip install watchdog
```

### Changes Not Detected

Make sure you're editing files in:
- `content/` directory
- `templates/` directory  
- `public/` directory

Changes to `dist/` are ignored (this is the build output).

## Workflow Tips

1. **Keep the terminal visible** - You'll see real-time feedback on rebuilds
2. **Use browser dev tools** - Console will show "✅ Live reload connected"
3. **Multiple tabs** - All open tabs to your site will refresh together
4. **Save often** - Each save triggers a rebuild, giving instant feedback

Enjoy faster development! 🚀


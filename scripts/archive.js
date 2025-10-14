#!/usr/bin/env node
/**
 * Auto-Archival Script
 * Archives published pages to Wayback Machine
 */

const https = require('https');
const fs = require('fs');
const path = require('path');

// Configuration
const SITE_URL = process.env.SITE_URL || 'https://example.com';
const RATE_LIMIT_MS = 4000; // 15 requests/minute = 1 request per 4 seconds

async function saveToWayback(url) {
  const saveUrl = `https://web.archive.org/save/${url}`;
  
  return new Promise((resolve, reject) => {
    https.get(saveUrl, (res) => {
      if (res.statusCode === 200) {
        // Extract memento URL from response headers
        const location = res.headers['content-location'] || res.headers['location'];
        resolve({
          url,
          archived: true,
          memento: location || saveUrl,
          timestamp: new Date().toISOString()
        });
      } else {
        resolve({
          url,
          archived: false,
          error: `HTTP ${res.statusCode}`,
          timestamp: new Date().toISOString()
        });
      }
    }).on('error', (err) => {
      resolve({
        url,
        archived: false,
        error: err.message,
        timestamp: new Date().toISOString()
      });
    });
  });
}

async function archiveSite(urls) {
  console.log('📦 Archiving pages to Wayback Machine...\n');
  
  const results = {
    site: SITE_URL,
    timestamp: new Date().toISOString(),
    archived: []
  };
  
  for (const url of urls) {
    const fullUrl = url.startsWith('http') ? url : `${SITE_URL}${url}`;
    
    try {
      console.log(`   Archiving: ${fullUrl}`);
      const result = await saveToWayback(fullUrl);
      results.archived.push(result);
      
      if (result.archived) {
        console.log(`   ✅ Saved: ${result.memento}`);
      } else {
        console.log(`   ❌ Failed: ${result.error}`);
      }
      
      // Rate limit
      await new Promise(resolve => setTimeout(resolve, RATE_LIMIT_MS));
    } catch (error) {
      console.error(`   ❌ Error: ${error.message}`);
      results.archived.push({
        url: fullUrl,
        archived: false,
        error: error.message,
        timestamp: new Date().toISOString()
      });
    }
  }
  
  // Save results
  const runsDir = path.join(__dirname, '..', 'runs');
  if (!fs.existsSync(runsDir)) {
    fs.mkdirSync(runsDir, { recursive: true });
  }
  
  const timestamp = new Date().toISOString().replace(/:/g, '-').split('.')[0];
  const outputPath = path.join(runsDir, `archive-${timestamp}.json`);
  fs.writeFileSync(outputPath, JSON.stringify(results, null, 2));
  
  console.log(`\n✅ Archive results saved to: ${outputPath}`);
  
  // Summary
  const successful = results.archived.filter(r => r.archived).length;
  const failed = results.archived.length - successful;
  
  console.log('\n📊 Summary:');
  console.log(`   Total: ${results.archived.length}`);
  console.log(`   Successful: ${successful}`);
  console.log(`   Failed: ${failed}`);
}

// Read URLs from args or sitemap
async function main() {
  const args = process.argv.slice(2);
  
  if (args.length === 0) {
    // Default: archive key pages
    const defaultUrls = [
      '/',
      '/posts/',
      '/projects/',
      '/products/',
      '/pages/about/'
    ];
    
    await archiveSite(defaultUrls);
  } else {
    // Archive provided URLs
    await archiveSite(args);
  }
}

// Run if called directly
if (require.main === module) {
  main().catch(error => {
    console.error('Fatal error:', error);
    process.exit(1);
  });
}

module.exports = { saveToWayback, archiveSite };


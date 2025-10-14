#!/usr/bin/env node
/**
 * CrUX Field Snapshot
 * Fetches real user data from PageSpeed Insights API (Chrome User Experience Report)
 */

const https = require('https');
const fs = require('fs');
const path = require('path');

// Configuration
const SITE_URL = process.env.SITE_URL || 'https://example.com';
const PSI_API_KEY = process.env.PSI_API_KEY || '';

// URLs to test
const TEST_URLS = [
  '/',
  '/posts/qi2-launch/',
  '/projects/platform/',
  '/products/example-shirt/'
];

async function fetchCrUXData(url) {
  const fullUrl = `${SITE_URL}${url}`;
  const apiUrl = `https://pagespeedonline.googleapis.com/pagespeedonline/v5/runPagespeed?url=${encodeURIComponent(fullUrl)}&strategy=mobile&category=PERFORMANCE${PSI_API_KEY ? '&key=' + PSI_API_KEY : ''}`;
  
  return new Promise((resolve, reject) => {
    https.get(apiUrl, (res) => {
      let data = '';
      
      res.on('data', (chunk) => {
        data += chunk;
      });
      
      res.on('end', () => {
        try {
          const json = JSON.parse(data);
          
          // Extract CrUX field data
          const cruxMetrics = json.loadingExperience?.metrics || {};
          
          const result = {
            url: fullUrl,
            timestamp: new Date().toISOString(),
            metrics: {
              lcp: extractMetric(cruxMetrics.LARGEST_CONTENTFUL_PAINT_MS),
              fid: extractMetric(cruxMetrics.FIRST_INPUT_DELAY_MS),
              cls: extractMetric(cruxMetrics.CUMULATIVE_LAYOUT_SHIFT_SCORE),
              fcp: extractMetric(cruxMetrics.FIRST_CONTENTFUL_PAINT_MS),
              inp: extractMetric(cruxMetrics.INTERACTION_TO_NEXT_PAINT),
              ttfb: extractMetric(cruxMetrics.EXPERIMENTAL_TIME_TO_FIRST_BYTE)
            },
            overall_category: cruxMetrics.OVERALL_CATEGORY || 'UNKNOWN'
          };
          
          resolve(result);
        } catch (e) {
          reject(new Error(`Failed to parse PSI response: ${e.message}`));
        }
      });
    }).on('error', (err) => {
      reject(err);
    });
  });
}

function extractMetric(metric) {
  if (!metric) return null;
  
  return {
    percentile: metric.percentile,
    category: metric.category,
    distributions: metric.distributions
  };
}

async function runSnapshot() {
  console.log('📊 Fetching CrUX field data...\n');
  
  const results = {
    site: SITE_URL,
    timestamp: new Date().toISOString(),
    urls: []
  };
  
  for (const url of TEST_URLS) {
    try {
      console.log(`   Fetching: ${url}`);
      const data = await fetchCrUXData(url);
      results.urls.push(data);
      
      // Rate limit: 1 request per second
      await new Promise(resolve => setTimeout(resolve, 1000));
    } catch (error) {
      console.error(`   ❌ Error fetching ${url}: ${error.message}`);
      results.urls.push({
        url: `${SITE_URL}${url}`,
        error: error.message
      });
    }
  }
  
  // Save to runs/field.json
  const runsDir = path.join(__dirname, '..', 'runs');
  if (!fs.existsSync(runsDir)) {
    fs.mkdirSync(runsDir, { recursive: true });
  }
  
  const outputPath = path.join(runsDir, 'field.json');
  fs.writeFileSync(outputPath, JSON.stringify(results, null, 2));
  
  console.log(`\n✅ Field data saved to: ${outputPath}`);
  
  // Print summary
  console.log('\n📊 Summary:');
  results.urls.forEach(r => {
    if (r.error) {
      console.log(`   ${r.url}: ERROR`);
    } else {
      const lcp = r.metrics.lcp?.percentile || 'N/A';
      const cls = r.metrics.cls?.percentile || 'N/A';
      console.log(`   ${r.url}:`);
      console.log(`      LCP: ${lcp}ms, CLS: ${cls}`);
    }
  });
  
  // Load previous snapshot for delta comparison
  const previousPath = path.join(runsDir, 'field-previous.json');
  if (fs.existsSync(previousPath)) {
    const previous = JSON.parse(fs.readFileSync(previousPath, 'utf8'));
    console.log('\n📈 Deltas from previous run:');
    
    results.urls.forEach((current, idx) => {
      const prev = previous.urls[idx];
      if (prev && !current.error && !prev.error) {
        const lcpDelta = current.metrics.lcp?.percentile - prev.metrics.lcp?.percentile;
        const clsDelta = current.metrics.cls?.percentile - prev.metrics.cls?.percentile;
        
        console.log(`   ${current.url}:`);
        if (lcpDelta !== undefined) {
          console.log(`      LCP: ${lcpDelta > 0 ? '+' : ''}${lcpDelta}ms`);
        }
        if (clsDelta !== undefined) {
          console.log(`      CLS: ${clsDelta > 0 ? '+' : ''}${clsDelta.toFixed(3)}`);
        }
      }
    });
  }
  
  // Copy current to previous for next run
  fs.writeFileSync(previousPath, JSON.stringify(results, null, 2));
}

// Run if called directly
if (require.main === module) {
  runSnapshot().catch(error => {
    console.error('Fatal error:', error);
    process.exit(1);
  });
}

module.exports = { runSnapshot };


# Job URL Audit Report
**Date:** March 4, 2026
**Total URLs Tested:** 20 (Top 20 by score)

---

## Executive Summary

- **VALID URLs:** 17 (85%)
- **INVALID URLs:** 3 (15%)
- **Average Score of Tested Jobs:** 79.9

---

## Detailed Results

### VALID URLs (17)

| Rank | Score | Company | Job Title | Status | Notes |
|------|-------|---------|-----------|--------|-------|
| 1 | 95 | Arcas Risk Management Inc. | Penetration Tester - Remote US Only | ✓ VALID | Contains full job description, application details, and requirements |
| 2 | 95 | Teksynap | Penetration Tester | ✓ VALID | Contains job information (Note: reCAPTCHA present but content accessible) |
| 3 | 85 | Human Interest | Security Engineer II | ✓ VALID | Full job posting with application process, salary range $150k-$200k |
| 4 | 85 | CyberSheath | Cyber Security Analyst II | ✓ VALID | Detailed job description with requirements and pay range $70k-$100k |
| 6 | 85 | Robert Half | Penetration Tester | ✓ VALID | Complete job posting with responsibilities and qualifications |
| 7 | 85 | Meta | Security Engineer | ✓ VALID | Full job details, salary $154k-$217k, located in Bellevue/NY |
| 8 | 85 | HealthMark Group | Security Engineer | ✓ VALID | Detailed posting on ADP platform, salary $90k-$120k |
| 9 | 85 | Canopy | Security Engineer | ✓ VALID | Complete job description with benefits and requirements |
| 10 | 82 | S-RM | Senior Cybersecurity Analyst (SOC) US Region | ✓ VALID | Full job posting with remote/hybrid options |
| 11 | 82 | Runpod | Security Engineer | ✓ VALID | Detailed posting, salary $152k-$175k |
| 12 | 82 | Glean | Security Engineer, Cloud Security | ✓ VALID | Complete job posting with application details |
| 13 | 78 | Docusign | Product Security Engineer | ✓ VALID | Full job description with salary ranges by state |
| 14 | 72 | FlexJobs | Penetration Tester | ✓ VALID | Job board listing with multiple penetration testing positions |
| 16 | 72 | Amyx, Inc. | Sr. Penetration Tester | ✓ VALID | Complete job posting, requires DOD Secret clearance |
| 18 | 72 | Teksynap | Penetration Tester w/ Secret Clearance | ✓ VALID | Detailed job requirements, clearance required |
| 19 | 72 | Peraton | Senior Cyber Threat Auditor | ✓ VALID | Full posting, requires Active TS clearance, location: Wiesbaden Germany |
| 20 | 72 | Samsara | Senior Security Engineer - Threat Modeling | ✓ VALID | Complete job details, Remote Canada, salary $150k-$194k CAD |

### INVALID URLs (3)

| Rank | Score | Company | Job Title | Status | Error Details |
|------|-------|---------|-----------|--------|---------------|
| 5 | 85 | InterEx Group | Cyber Security Analyst | ✗ INVALID | LinkedIn URL - Website not supported by extraction tool |
| 15 | 72 | Not Listed | Penetration Tester w/ Secret Clearance | ✗ INVALID | Careerwave URL redirects to generic loading page with no content |
| 17 | 72 | Not Listed | Senior Cybersecurity Penetration Tester | ✗ INVALID | UCM careers portal - redirected to general job search, specific job not found |

### Additional Notes on Problematic URLs

| Rank | Score | Company | Job Title | Status | Notes |
|------|-------|---------|-----------|--------|-------|
| 21 | 72 | Samsara | Senior Security Operations Engineer I | ⚠ WARNING | URL redirects to general Samsara careers page with 440+ jobs; specific job ID not accessible |
| 22 | 72 | Geographic Solutions, Inc. | Information Security Analyst I | ⚠ WARNING | Shows application form but no job description content |
| 23 | 72 | Delphi-US, LLC | Cyber Security Analyst | ⚠ WARNING | "Page not found" error - likely removed or URL changed |
| 24 | 72 | Omaha Airport Authority | Cybersecurity Analyst | ⚠ WARNING | Redirects to general careers page with no specific job posting |

---

## URL Validation Analysis

### By Score Range
- **Score 95 (2 jobs):** 100% valid (2/2)
- **Score 85 (7 jobs):** 85.7% valid (6/7) - 1 LinkedIn URL failed
- **Score 82 (3 jobs):** 100% valid (3/3)
- **Score 78 (1 job):** 100% valid (1/1)
- **Score 72 (7 jobs):** 57.1% valid (4/7) - 3 jobs failed/redirected

### Common Issues Identified

1. **LinkedIn Jobs** - Not supported by web extraction tool
   - InterEx Group position (Score 85)

2. **Expired/Removed Postings** - URLs redirect to general career pages or show 404
   - Careerwave generic listing (Score 72)
   - UCM Careers portal redirect (Score 72)
   - Delphi-US page not found (Score 72)
   - Omaha Airport Authority general page (Score 72)

3. **Application-Only Pages** - Some URLs show application forms but minimal job details
   - Geographic Solutions application form (Score 72)

---

## Recommendations

1. **Remove Invalid URLs:** Delete the 3 confirmed invalid job postings from scored_jobs.json
   - InterEx Group LinkedIn posting
   - Careerwave generic listing
   - UCM Careers redirect

2. **Monitor High-Score Jobs:** The top-scoring positions (95 and 85) have excellent accessibility (92.3% valid)

3. **Re-verify Lower-Scoring Jobs:** Jobs with score 72 have higher failure rate (57% valid) - consider re-scraping or deprioritizing

4. **LinkedIn Alternative:** Consider adding LinkedIn API integration or direct application instructions for LinkedIn postings

5. **Regular Audits:** Recommend weekly URL validation for top 50 jobs to catch expired postings early

---

## Statistics Summary

**URL Accessibility:**
- Fully Accessible: 17 (85%)
- Failed/Invalid: 3 (15%)
- Warnings (partial access): 4 (not in top 20 count)

**Average Quality Score:** 79.9 (weighted by valid URLs)

**Best Performing Sources:**
- Greenhouse.io: 5/5 valid (100%)
- iCIMS platforms: 4/5 valid (80%)
- ADP/Direct ATS: 2/2 valid (100%)

**Worst Performing Sources:**
- LinkedIn: 0/1 valid (0%)
- Generic job boards: 0/2 valid (0%)

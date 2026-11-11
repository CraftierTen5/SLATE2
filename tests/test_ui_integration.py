"""Static guards for the small auth/jobs/roadmap UI integration."""
from pathlib import Path
HTML = (Path(__file__).resolve().parents[1] / 'web' / 'index.html').read_text()

def test_freshness_discloses_fixture_meaning_beside_state():
    assert 'Demo fixture: ${esc(x.freshness||"unknown")} (not live-verified)' in HTML

def test_match_reason_and_job_id_are_escaped():
    assert '${esc(x.reason||"")}' in HTML
    assert 'data-j="${esc(x.jobId)}"' in HTML

def test_roadmap_resources_remain_https_links():
    assert 'm.resources.map(resLink)' in HTML
    assert 'rel="noopener noreferrer"' in HTML
    assert r'/^https:\/\//' in HTML

def test_auth_still_covers_json_and_pdf_requests():
    assert 'h["authorization"]="Bearer "+token()' in HTML
    assert 'ph["authorization"]="Bearer "+token()' in HTML

def test_dedicated_interview_page_has_voice_and_resume_controls():
    page=(Path(__file__).resolve().parents[1]/"web"/"interview.html").read_text()
    assert 'fetch("/v1"+path' in page
    assert 'mode:sessionMode' in page
    assert 'resumeId:$("resume").value||null' in page
    assert 'SpeechRecognition||window.webkitSpeechRecognition' in page
    assert 'answerReviews' in page or 'fb.answerReviews' in page


def test_interview_ui_has_camera_voice_delivery_and_manual_end_controls():
    page=(Path(__file__).resolve().parents[1]/"web"/"interview.html").read_text()
    assert 'getUserMedia({video:' in page
    assert 'MediaRecorder' in page
    assert 'measureDelivery' in page
    assert 'pitchRangeHz' in page
    assert 'deliveryMetrics' in page
    assert '"/end"' in page
    assert 'id="endInterview"' in page
    assert 'No video is uploaded or recorded' in page


def test_every_workspace_part_has_a_distinct_route_and_nav():
    for part in ('resume','targets','draft','comparisons','roadmap'):
        assert 'data-part="'+part+'"' in HTML
    assert 'pageParts={resume:["s1"],targets:["targetWorkspace"],draft:["s3"],comparisons:["s2"],roadmap:["s4"]}' in HTML
    assert 'crypto.subtle.digest("SHA-256",bytes)' in HTML
    assert 'beforeunload' in HTML

def test_live_feed_copy_discloses_mentions_geography_and_freshness():
    assert '% mention overlap (extracted)' in HTML
    assert 'Live job board listings' in HTML
    assert 'not because every role is India-eligible - read each posting' in HTML
    assert "that age is why it shows 'stale', not a removal" in HTML
    assert "employer's posting unchanged since " in HTML

def test_sample_feed_literals_remain_for_fixture_mode():
    assert 'Sample job comparisons' in HTML
    assert 'over 5 sample listings' in HTML
    assert '% skill overlap' in HTML
    assert 'Explore five sample listings' in HTML

def test_route_header_has_live_mode_copy():
    assert 'Explore / Live boards' in HTML
    assert 'Explore / Sample data' in HTML
    assert 'Live listings from public job boards. Mention overlap is a literal text check, not an employability score.' in HTML
    assert 'jobSource==="live"' in HTML

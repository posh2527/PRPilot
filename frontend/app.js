
const BACKEND_URL = "http://127.0.0.1:8010";
const PRS_API_URL = `${BACKEND_URL}/api/prs`;
const AUTH_ME_URL = `${BACKEND_URL}/api/auth/me`;
const INSTALLATIONS_URL = `${BACKEND_URL}/api/installations`;
const REPOSITORIES_URL = `${BACKEND_URL}/api/repositories`;
const REFRESH_INTERVAL = 30000;
const SELECTED_INSTALLATION_KEY = "prpilot_selected_installation_id";
const SELECTED_REPOSITORY_KEY = "prpilot_selected_repository";

const fallbackPRs = [
  { owner: "octo-labs", repo: "auth-service", pr_number: 184, title: "Handle special characters in login passwords", author: "maya-chen", description: "Handle special characters correctly during login validation.", changed_files: ["src/auth/login.js", "tests/auth/login.test.js"], changed_file_count: 2, code_file_count: 1, test_file_count: 1, issue_linked: true, description_match: "High", summary: ["Fixes password parsing for special characters.", "Includes regression coverage for login validation."], checklist: [], recommendation: "Ready for Review", timestamp: 1758364800 },
  { owner: "octo-labs", repo: "checkout", pr_number: 92, title: "Improve checkout error handling", author: "dev-reviewer", description: "Improve checkout errors for failed payments.", changed_files: ["src/checkout/errors.js"], changed_file_count: 1, code_file_count: 1, test_file_count: 0, issue_linked: false, summary: ["Description mentions code changes, but no test files were modified.", "No linked issue or bug report found."], checklist: ["Link an issue or bug report.", "Add or update tests for this change."], recommendation: "Needs Changes", timestamp: 1758278400 },
  { owner: "octo-labs", repo: "docs", pr_number: 31, title: "Update README spacing", author: "docs-helper", description: "Small formatting changes to the README.", changed_files: ["README.md"], changed_file_count: 1, code_file_count: 0, test_file_count: 0, issue_linked: false, description_match: "Low", summary: ["The change appears limited to minor formatting updates.", "No meaningful product or documentation content detected."], checklist: ["Confirm this change is needed or include the related issue context."], recommendation: "Low-value / Unclear", timestamp: 1758192000 }
];

let prs = [];
let installations = [];
let currentUser = null;
let selectedInstallation = null;
let selectedRepository = null;
let activeFilter = "all";
let isLoading = false;
let demoMode = false;
const elements = {};

document.addEventListener("DOMContentLoaded", () => {
  const ids = ["demoNotice", "loading", "empty", "error", "prContainer", "refreshButton", "retryButton", "lastUpdated", "dashboard", "analysis", "onboarding", "login", "accounts", "repositorySelector", "success", "onboardingError", "connectedRepository", "connectedRepositoryName", "installPanelToggle", "closeInstallPanel", "panelError"];
  const domIds = ["demo-notice", "loading-state", "empty-state", "error-state", "pr-container", "refresh-button", "retry-button", "last-updated", "dashboard-view", "analysis-view", "onboarding-view", "onboarding-login", "account-selection-view", "repository-selector", "connection-success", "onboarding-error", "connected-repository", "connected-repository-name", "install-panel-toggle", "close-install-panel", "panel-error"];
  ids.forEach((key, index) => { elements[key] = document.getElementById(domIds[index]); });
  resetDashboardStates();
  elements.refreshButton.addEventListener("click", fetchPRs);
  elements.retryButton.addEventListener("click", fetchPRs);
  document.getElementById("continue-github").addEventListener("click", () => { window.location.href = `${BACKEND_URL}/api/auth/github/login`; });
  document.getElementById("continue-demo").addEventListener("click", enterDemoMode);
  ["install-account", "install-empty", "install-more-repositories", "manage-connection"].forEach((id) => document.getElementById(id).addEventListener("click", installOnAnotherAccount));
  document.getElementById("sign-out-account").addEventListener("click", logout);
  document.getElementById("disconnect-repository").addEventListener("click", logout);
  document.getElementById("change-repository").addEventListener("click", switchRepository);
  document.getElementById("back-to-accounts").addEventListener("click", showAccountSelectionView);
  document.getElementById("open-dashboard").addEventListener("click", showDashboard);
  elements.closeInstallPanel.addEventListener("click", closeInstallPanel);
  elements.installPanelToggle.addEventListener("click", () => { renderAccountSelection(); openInstallPanel(); });
  document.getElementById("repository-form").addEventListener("submit", (event) => { event.preventDefault(); const input = document.querySelector("input[name='repository']:checked"); if (input) selectRepository(input.value); });
  document.getElementById("filter-container").addEventListener("click", (event) => { const button = event.target.closest("button[data-filter]"); if (!button) return; activeFilter = button.dataset.filter || "all"; renderFilters(); renderPRCards(); });
  initializeApp();
  window.setInterval(fetchPRs, REFRESH_INTERVAL);
});

function storageGet(key) { try { return localStorage.getItem(key); } catch (error) { return null; } }
function storageSet(key, value) { try { localStorage.setItem(key, value); } catch (error) { return false; } return true; }
function storageRemove(key) { try { localStorage.removeItem(key); } catch (error) { return false; } return true; }
function getStoredSelectedInstallation() { return storageGet(SELECTED_INSTALLATION_KEY); }
function getStoredSelectedRepository() { return storageGet(SELECTED_REPOSITORY_KEY); }
function clearSelectedRepository() { storageRemove(SELECTED_INSTALLATION_KEY); storageRemove(SELECTED_REPOSITORY_KEY); selectedInstallation = null; selectedRepository = null; }

async function initializeApp() {
  const user = await checkAuthentication();
  if (!user) { showConnectGitHubView(); return; }
  currentUser = user;
  fetchInstallations();
}

async function checkAuthentication() {
  try {
    const response = await fetch(AUTH_ME_URL, { credentials: "include" });
    if (response.status === 401) { clearSelectedRepository(); return null; }
    if (!response.ok) throw new Error("Authentication service unavailable");
    const payload = await response.json();
    return payload.authenticated && payload.user ? payload.user : null;
  } catch (error) { showLocalDevelopmentPrompt(); return null; }
}

function hideAllOnboardingStates() { [elements.login, elements.accounts, elements.repositorySelector, elements.success].forEach((view) => { view.hidden = true; }); }
function resetDashboardStates() { elements.loading.hidden = true; elements.error.hidden = true; elements.empty.hidden = true; elements.prContainer.hidden = true; }
function hideDashboardViews() { elements.dashboard.hidden = true; elements.analysis.hidden = true; elements.connectedRepository.hidden = true; resetDashboardStates(); }
function showConnectGitHubView() { demoMode = false; document.body.classList.add("onboarding-mode"); elements.onboarding.hidden = false; hideDashboardViews(); hideAllOnboardingStates(); elements.login.hidden = false; setInstallToggleVisible(false); }
function showAccountSelectionView() { if (!currentUser) return showConnectGitHubView(); document.body.classList.remove("onboarding-mode"); elements.onboarding.hidden = true; elements.connectedRepository.hidden = false; elements.connectedRepositoryName.textContent = `Connected repository: ${selectedRepository || "None selected yet"}`; document.getElementById("connected-account-name").textContent = `Connected account: ${selectedInstallation?.account_login || currentUser.login || "GitHub"}`; document.getElementById("dashboard-user").innerHTML = avatarMarkup(currentUser.avatar_url, currentUser.login); renderDashboard(); hideAllOnboardingStates(); renderAccountSelection(); openInstallPanel(); }
function openInstallPanel() { elements.accounts.hidden = false; setInstallToggleVisible(false); }
function closeInstallPanel() { elements.accounts.hidden = true; setInstallToggleVisible(Boolean(currentUser) && !demoMode && !document.body.classList.contains("onboarding-mode")); }
function setInstallToggleVisible(visible) { elements.installPanelToggle.hidden = !visible; document.body.classList.toggle("install-toggle-visible", Boolean(visible)); }
function showRepositorySelectionView() { if (!selectedInstallation) return showAccountSelectionView(); setInstallToggleVisible(false); document.body.classList.add("onboarding-mode"); elements.onboarding.hidden = false; hideDashboardViews(); hideAllOnboardingStates(); elements.repositorySelector.hidden = false; renderRepositorySelection(); }

async function fetchInstallations() {
  try {
    const response = await fetch(INSTALLATIONS_URL, { credentials: "include" });
    if (response.status === 401) { clearSelectedRepository(); showConnectGitHubView(); return; }
    if (!response.ok) throw new Error("Installations request failed");
    const payload = await response.json();
    installations = Array.isArray(payload) ? payload : (Array.isArray(payload.installations) ? payload.installations : []);
    if (installations.some((installation) => !Array.isArray(installation.repositories))) {
      const repositoriesResponse = await fetch(REPOSITORIES_URL, { credentials: "include" });
      if (repositoriesResponse.ok) {
        const repositories = await repositoriesResponse.json();
        installations = installations.map((installation) => ({ ...installation, repositories: Array.isArray(installation.repositories) ? installation.repositories : repositories.map((repository) => ({ full_name: repository.full_name, private: repository.private, description: repository.description })) }));
      }
    }
    const storedRepository = getStoredSelectedRepository();
    const storedInstallation = getStoredSelectedInstallation();
    const authorizedInstallation = installations.find((installation) => String(installation.id) === String(storedInstallation) && installation.repositories?.some((repository) => repository.full_name === storedRepository));
    if (storedRepository && authorizedInstallation) { selectedInstallation = authorizedInstallation; selectedRepository = storedRepository; showDashboard(); return; }
    if (storedRepository) clearSelectedRepository();
    showAccountSelectionView();
  } catch (error) { showAccountSelectionView(); showOnboardingError("We could not load your GitHub accounts. Check the backend connection and try again."); }
}

function renderAccountSelection() {
  const list = document.getElementById("account-list");
  elements.onboardingError.hidden = true;
  elements.panelError.hidden = true;
  document.getElementById("signed-in-user").innerHTML = currentUser ? `${avatarMarkup(currentUser.avatar_url, currentUser.name || currentUser.login)}<span>${escapeHTML(currentUser.name || currentUser.login)}<small>@${escapeHTML(currentUser.login || "")}</small></span>` : "";
  document.getElementById("empty-installation").hidden = installations.length > 0;
  list.hidden = installations.length === 0;
  list.innerHTML = installations.map((item) => `<article class="account-option"><div class="account-info">${avatarMarkup(item.account_avatar_url, item.account_login)}<div><strong>${escapeHTML(item.account_login)}</strong><span class="account-type">${item.account_type === "Organization" ? "Organization" : "Personal Account"}</span><small>${item.repositories?.length || 0} repositories available</small></div></div><button class="primary-button" type="button" data-installation-id="${escapeHTML(String(item.id))}">Choose this account <span aria-hidden="true">&#8594;</span></button></article>`).join("");
  list.querySelectorAll("[data-installation-id]").forEach((button) => button.addEventListener("click", () => selectInstallation(button.dataset.installationId)));
}

function selectInstallation(id) { selectedInstallation = installations.find((item) => String(item.id) === String(id)) || null; selectedRepository = null; if (selectedInstallation) showRepositorySelectionView(); }
function renderRepositorySelection() {
  const account = selectedInstallation;
  document.getElementById("selected-account-header").innerHTML = `${avatarMarkup(account.account_avatar_url, account.account_login)}<span><strong>${escapeHTML(account.account_login)}</strong><small>${account.account_type === "Organization" ? "Organization" : "Personal Account"}</small></span>`;
  const options = document.getElementById("repository-options");
  const repositories = Array.isArray(account.repositories) ? account.repositories : [];
  options.innerHTML = repositories.length ? repositories.map((repository, index) => `<label class="repository-option${index === 0 ? " selected" : ""}"><input type="radio" name="repository" value="${escapeHTML(repository.full_name)}" ${index === 0 ? "checked" : ""}><span class="repo-icon" aria-hidden="true">&#128193;</span><span class="repo-copy"><strong>${escapeHTML(repository.full_name)}</strong><small>${escapeHTML(repository.description || "No description available.")}</small></span><span class="repo-visibility">${repository.private ? "Private" : "Public"}</span><span class="repo-check" aria-hidden="true">&#10003;</span></label>`).join("") : `<p class="muted-copy">No repositories are available for this account yet.</p>`;
  options.querySelectorAll("input[name='repository']").forEach((input) => input.addEventListener("change", () => options.querySelectorAll(".repository-option").forEach((option) => option.classList.toggle("selected", option.contains(input) && input.checked))));
}
function selectRepository(repositoryName) { selectedRepository = repositoryName; storageSet(SELECTED_INSTALLATION_KEY, String(selectedInstallation.id)); storageSet(SELECTED_REPOSITORY_KEY, repositoryName); showDashboard(); }
function switchRepository() { clearSelectedRepository(); prs = []; fetchInstallations(); }
function installOnAnotherAccount() { window.location.href = `${BACKEND_URL}/api/github/install`; }
async function logout() { try { await fetch(`${BACKEND_URL}/api/auth/logout`, { method: "POST", credentials: "include" }); } catch (error) { /* Signed-out UI remains available if the backend is unavailable. */ } clearSelectedRepository(); currentUser = null; demoMode = false; prs = []; showConnectGitHubView(); }
function showDashboard() { if (!selectedRepository && !demoMode) selectedRepository = getStoredSelectedRepository(); if (!selectedRepository && !demoMode) return showAccountSelectionView(); document.body.classList.remove("onboarding-mode"); elements.onboarding.hidden = true; elements.dashboard.hidden = false; elements.analysis.hidden = true; elements.connectedRepository.hidden = false; elements.connectedRepositoryName.textContent = `Connected repository: ${selectedRepository || "PRPilot demo repository"}`; document.getElementById("connected-account-name").textContent = demoMode ? "Local development mode" : `Connected account: ${selectedInstallation?.account_login || currentUser?.login || "GitHub"}`; document.getElementById("dashboard-user").innerHTML = currentUser ? `${avatarMarkup(currentUser.avatar_url, currentUser.login)} @${escapeHTML(currentUser.login || "")}` : "Demo workspace"; if (!prs.length) fetchPRs(); closeInstallPanel(); window.scrollTo({ top: 0, behavior: "smooth" }); }
function enterDemoMode() { demoMode = true; selectedRepository = "PRPilot demo repository"; currentUser = { login: "demo-maintainer", name: "Demo maintainer" }; elements.onboarding.hidden = false; hideAllOnboardingStates(); elements.success.hidden = false; }
function showLocalDevelopmentPrompt() { showOnboardingError("Local development mode: authentication APIs are unavailable. Continue in demo mode to preview the dashboard."); }
function showOnboardingError(message) { elements.onboardingError.textContent = message; elements.onboardingError.hidden = false; elements.panelError.textContent = message; elements.panelError.hidden = false; }
function avatarMarkup(url, name) { const initials = String(name || "GH").split(/\s+/).map((part) => part[0]).join("").slice(0, 2).toUpperCase(); return url ? `<img class="avatar" src="${escapeHTML(url)}" alt="">` : `<span class="avatar avatar-fallback" aria-hidden="true">${escapeHTML(initials)}</span>`; }

async function fetchPRs() {
  if (isLoading) return;
  isLoading = true; showLoading(); elements.refreshButton.disabled = true;
  try {
    const response = await fetch(PRS_API_URL, { credentials: "include", headers: { Accept: "application/json" } });
    if (response.status === 401) { clearSelectedRepository(); throw new Error("Your GitHub session has expired. Sign in again to load pull requests."); }
    if (response.status === 403) throw new Error("You do not have access to this repository.");
    if (!response.ok) throw new Error(`The backend returned an unexpected response (HTTP ${response.status}).`);
    const data = await response.json();
    if (!data || !Array.isArray(data.prs)) throw new Error("The backend response did not include a pull request list.");
    prs = normalizePRs(data.prs);
    elements.demoNotice.hidden = true;
    renderDashboard();
  } catch (error) {
    console.error("PRPilot could not load pull requests:", error);
    if (demoMode) { prs = normalizePRs(fallbackPRs); elements.demoNotice.hidden = false; renderDashboard(); }
    else showError(errorMessage(error));
  } finally { isLoading = false; elements.refreshButton.disabled = false; }
}

function normalizePRs(items) { return items.map((item) => ({ ...item, owner: typeof item?.owner === "string" ? item.owner : "unknown-owner", repo: typeof item?.repo === "string" ? item.repo : "unknown-repo", pr_number: item?.pr_number ?? "", title: typeof item?.title === "string" && item.title.trim() ? item.title : "Untitled pull request", author: typeof item?.author === "string" ? item.author : "", description: typeof item?.description === "string" ? item.description : "", changed_files: Array.isArray(item?.changed_files) ? item.changed_files.filter((entry) => typeof entry === "string") : [], summary: Array.isArray(item?.summary) ? item.summary.filter((entry) => typeof entry === "string") : [], checklist: Array.isArray(item?.checklist) ? item.checklist.filter((entry) => typeof entry === "string") : [], recommendation: typeof item?.recommendation === "string" ? item.recommendation : "Needs Fixes", timestamp: item?.timestamp })).sort((a, b) => toTimestamp(b.timestamp) - toTimestamp(a.timestamp)); }
function renderDashboard() { elements.loading.hidden = true; elements.error.hidden = true; elements.dashboard.hidden = false; elements.analysis.hidden = true; renderStats(); renderFilters(); renderPRCards(); renderInsights(); elements.lastUpdated.textContent = `Last updated: ${formatTimestamp(Date.now() / 1000)}`; }
function renderStats() { const counts = { ready: 0, changes: 0, low: 0 }; prs.forEach((pr) => { counts[getStatusType(pr.recommendation)] += 1; }); document.getElementById("total-count").textContent = prs.length; document.getElementById("ready-count").textContent = counts.ready; document.getElementById("changes-count").textContent = counts.changes; document.getElementById("low-count").textContent = counts.low; document.getElementById("all-filter-count").textContent = prs.length; }
function renderFilters() { document.querySelectorAll(".filter-button").forEach((button) => { const active = button.dataset.filter === activeFilter; button.classList.toggle("active", active); button.setAttribute("aria-pressed", String(active)); }); }
function renderPRCards() { const visible = prs.filter((pr) => activeFilter === "all" || getStatusType(pr.recommendation) === activeFilter); elements.prContainer.innerHTML = visible.map(createPRCard).join(""); elements.empty.hidden = prs.length !== 0 || isLoading; elements.prContainer.hidden = visible.length === 0; }
function createPRCard(pr) { const status = getStatusType(pr.recommendation); const label = status === "ready" ? "Ready for detailed review" : status === "low" ? "Needs attention" : "Needs fixes"; const signals = getSignals(pr); return `<article class="pr-card status-${status}"><div class="pr-card-header"><div><p class="pr-number">PR #${escapeHTML(String(pr.pr_number))}</p><h3 class="pr-title"><a href="${getGithubURL(pr)}" target="_blank" rel="noopener noreferrer">${escapeHTML(pr.title)}</a></h3></div><span class="recommendation ${status}">${label}</span></div><div class="pr-meta"><span aria-label="Repository">&#128193; ${escapeHTML(pr.owner)}/${escapeHTML(pr.repo)}</span><span aria-label="Contributor">&#9679; ${escapeHTML(pr.author || "Unknown contributor")}</span></div><div class="quick-signals"><span class="signal"><strong>Description match</strong><em>${escapeHTML(signals.description)}</em></span><span class="signal"><strong>Tests</strong><em>${escapeHTML(signals.tests)}</em></span><span class="signal"><strong>Issue</strong><em>${escapeHTML(signals.issue)}</em></span></div><button class="analysis-button" type="button" data-pr-key="${escapeHTML(getPRKey(pr))}">View analysis <span aria-hidden="true">&#8594;</span></button></article>`; }
function renderInsights() { const noIssue = prs.filter((pr) => getSignals(pr).issue === "Not linked").length; const noTests = prs.filter((pr) => getSignals(pr).tests === "Not found").length; const lowMatch = prs.filter((pr) => getSignals(pr).description === "Low").length; document.getElementById("reviewed-count").textContent = prs.length; document.getElementById("no-issue-count").textContent = noIssue; document.getElementById("no-tests-count").textContent = noTests; document.getElementById("low-match-count").textContent = lowMatch; document.getElementById("time-saved").textContent = formatMinutes(prs.length * 5); }
function getStatusType(recommendation) { const value = String(recommendation || "").toLowerCase(); if (value.includes("ready")) return "ready"; if (value.includes("attention") || value.includes("low") || value.includes("unclear") || value.includes("spam")) return "low"; return "changes"; }
function getSignals(pr) { const text = [...pr.summary, ...pr.checklist].join(" ").toLowerCase(); const description = normalizeSignal(pr.description_match, text.includes("only") || text.includes("no meaningful") ? "Low" : text.includes("description") ? "Partial" : ""); const tests = pr.test_file_count !== undefined ? (Number(pr.test_file_count) > 0 ? "Found" : "Not found") : text.includes("test") ? "Not found" : "Not available"; const issue = typeof pr.issue_linked === "boolean" ? (pr.issue_linked ? "Linked" : "Not linked") : text.includes("no linked issue") || text.includes("link an issue") ? "Not linked" : "Not available"; return { description: description || "Not analyzed", tests, issue }; }
function normalizeSignal(value, inferred) { if (typeof value === "string") { const normalized = value.toLowerCase(); if (normalized.includes("high")) return "High"; if (normalized.includes("partial")) return "Partial"; if (normalized.includes("low")) return "Low"; } return inferred; }

function showAnalysis(pr) { elements.dashboard.hidden = true; elements.analysis.hidden = false; elements.analysis.innerHTML = createAnalysisView(pr); elements.analysis.querySelector("[data-action='back']").addEventListener("click", renderDashboard); elements.analysis.querySelector("[data-action='github']").addEventListener("click", () => window.open(getGithubURL(pr), "_blank", "noopener,noreferrer")); }
function createAnalysisView(pr) { const status = getStatusType(pr.recommendation); const signals = getSignals(pr); const files = pr.changed_files.length ? `<ul class="file-list">${pr.changed_files.map((file) => `<li>${escapeHTML(file)}</li>`).join("")}</ul>` : `<p class="muted-copy">Changed-file details unavailable from the current backend response.</p>`; const changedCount = pr.changed_file_count ?? (pr.changed_files.length || "Not available"); return `<div class="analysis-shell"><button class="back-button" type="button" data-action="back">&#8592; Back to dashboard</button><div class="analysis-header"><div><p class="pr-number">PR #${escapeHTML(String(pr.pr_number))}</p><h2 id="analysis-title">${escapeHTML(pr.title)}</h2><p class="analysis-repo">${escapeHTML(pr.owner)}/${escapeHTML(pr.repo)} &middot; ${escapeHTML(pr.author || "Unknown contributor")}</p></div><span class="recommendation ${status}">${escapeHTML(pr.recommendation)}</span></div><div class="analysis-actions"><button class="github-button" type="button" data-action="github">Open GitHub PR &#8599;</button></div><section class="description-panel"><h3>PR description</h3><p>${escapeHTML(pr.description || "No PR description available.")}</p></section><div class="analysis-grid"><section class="analysis-panel"><p class="eyebrow blue-eyebrow">What changed</p><h3>Change footprint</h3><div class="change-counts"><div><strong>${escapeHTML(String(changedCount))}</strong><span>Files changed</span></div><div><strong>${escapeHTML(String(pr.code_file_count ?? "Not available"))}</strong><span>Code files</span></div><div><strong>${escapeHTML(String(pr.test_file_count ?? "Not available"))}</strong><span>Test files</span></div></div>${files}</section><section class="analysis-panel"><p class="eyebrow blue-eyebrow">PRPilot analysis</p><h3>Quality signals</h3><div class="quality-list"><div><span>Description-change match</span><strong>${escapeHTML(signals.description)}</strong></div><div><span>Issue linked</span><strong>${escapeHTML(signals.issue)}</strong></div><div><span>Tests included</span><strong>${escapeHTML(signals.tests)}</strong></div></div><ul class="analysis-summary">${renderList(pr.summary, "No summary available.")}</ul></section></div><section class="analysis-panel"><p class="eyebrow blue-eyebrow">Suggested actions</p><h3>Recommended next steps</h3><ul class="action-list">${renderCheckboxList(pr.checklist, "No suggested fixes.")}</ul></section><section class="final-recommendation status-${status}"><div><p class="eyebrow">Final recommendation</p><h3>${getFinalRecommendation(status)}</h3></div><span class="recommendation ${status}">${escapeHTML(pr.recommendation)}</span></section></div>`; }
function getFinalRecommendation(status) { return status === "ready" ? "Ready for detailed maintainer review." : status === "low" ? "Inspect carefully and request clarification before merging." : "Request the suggested fixes before merging."; }
function renderCheckboxList(items, emptyText) { const safeItems = Array.isArray(items) && items.length ? items : [emptyText]; return safeItems.map((item) => `<li><span class="checkbox" aria-hidden="true"></span>${escapeHTML(item)}</li>`).join(""); }
function renderList(items, emptyText) { const safeItems = Array.isArray(items) && items.length ? items : [emptyText]; return safeItems.map((item) => `<li>${escapeHTML(item)}</li>`).join(""); }
function getPRKey(pr) { return `${pr.owner}/${pr.repo}#${pr.pr_number}`; }
function getGithubURL(pr) { return typeof pr.github_url === "string" && pr.github_url.startsWith("https://github.com/") ? pr.github_url : `https://github.com/${encodeURIComponent(pr.owner)}/${encodeURIComponent(pr.repo)}/pull/${encodeURIComponent(pr.pr_number)}`; }
function escapeHTML(value) { return String(value ?? "").replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[character])); }
function formatTimestamp(timestamp) { const value = toTimestamp(timestamp); if (!value) return "time unavailable"; return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value * 1000)); }
function formatMinutes(minutes) { return minutes >= 60 ? `${Math.floor(minutes / 60)}h ${minutes % 60}m` : `${minutes}m`; }
function toTimestamp(timestamp) { const value = Number(timestamp); return Number.isFinite(value) && value > 0 ? value : 0; }
function showLoading() { elements.loading.hidden = false; elements.error.hidden = true; elements.empty.hidden = true; elements.prContainer.hidden = true; }
function showError(message) { elements.loading.hidden = true; elements.empty.hidden = true; elements.error.hidden = false; elements.prContainer.hidden = true; const paragraph = elements.error.querySelector("p"); if (paragraph && message) paragraph.textContent = message; }
function errorMessage(error) { const raw = error instanceof Error ? error.message : ""; if (!raw || raw === "Failed to fetch" || raw.includes("NetworkError") || raw.includes("Load failed")) return "We could not load pull requests. Check the backend connection and try again."; return raw; }

document.addEventListener("click", (event) => { const button = event.target.closest("[data-pr-key]"); if (!button) return; const pr = prs.find((item) => getPRKey(item) === button.dataset.prKey); if (pr) showAnalysis(pr); });

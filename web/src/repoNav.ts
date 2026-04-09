import type { NavigateFunction } from "react-router-dom";
import * as api from "./api";

/**
 * Tracks the most recent repo navigation target.  When multiple calls race
 * (e.g. user clicks repo A then repo B), only the latest one navigates —
 * earlier promises check this value and bail out if it has changed.
 */
let _lastRepoNavTarget: string | null = null;

/**
 * Fetch conversations for `repoName`, sort by most-recently-updated, and
 * navigate to the first one.  Falls back to the bare repo URL when no
 * conversations exist or the fetch fails.
 *
 * Handles rapid successive calls safely — only the most recent target
 * actually triggers navigation.
 */
export function navigateToRepo(repoName: string, navigate: NavigateFunction): void {
  _lastRepoNavTarget = repoName;

  api.fetchConversations(repoName).then((convos) => {
    if (_lastRepoNavTarget !== repoName) return; // stale — user clicked another repo
    const sorted = [...convos].sort(
      (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
    );
    const first = sorted[0];
    if (first) {
      navigate(`/${encodeURIComponent(repoName)}/c/${encodeURIComponent(first.id)}`);
    } else {
      navigate(`/${encodeURIComponent(repoName)}`);
    }
  }).catch(() => {
    if (_lastRepoNavTarget !== repoName) return;
    navigate(`/${encodeURIComponent(repoName)}`);
  });
}

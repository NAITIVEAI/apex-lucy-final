// Agent Portal JavaScript

document.addEventListener("DOMContentLoaded", function () {
  // Elements
  const pendingList = document.getElementById("pending-list");
  const noPending = document.getElementById("no-pending");
  const refreshBtn = document.getElementById("refresh-btn");
  const lastUpdated = document.getElementById("last-updated");
  const timezoneInfo = document.getElementById("timezone-info");

  // Display current timezone
  if (timezoneInfo) {
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    const now = new Date();
    const tzName = now
      .toLocaleTimeString([], { timeZoneName: "short" })
      .split(" ")
      .pop();
    timezoneInfo.textContent = `Timezone: ${tzName} (${tz})`;
  }

  // Initialize
  fetchPendingConversations();

  // Set up auto-refresh every 15 seconds
  const refreshInterval = setInterval(fetchPendingConversations, 15000);

  // Manual refresh button
  refreshBtn.addEventListener("click", function () {
    refreshBtn.disabled = true;
    refreshBtn.innerHTML = "Refreshing...";
    fetchPendingConversations().then(() => {
      refreshBtn.disabled = false;
      refreshBtn.innerHTML = "Refresh";
    });
  });

  // Fetch pending conversations from the API
  async function fetchPendingConversations() {
    try {
      const response = await fetch("/api/conversations/pending");
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const conversations = await response.json();
      renderConversations(conversations);
      updateLastUpdated();

      return conversations;
    } catch (error) {
      console.error("Error fetching conversations:", error);
      pendingList.innerHTML = `
                <tr>
                    <td colspan="8" class="px-6 py-4 text-sm text-red-500 text-center">
                        Error loading conversations. Please try again.
                    </td>
                </tr>
            `;
    }
  }

  // Render conversations in the table
  function renderConversations(conversations) {
    if (conversations.length === 0) {
      pendingList.innerHTML = "";
      pendingList.parentElement.parentElement.classList.add("hidden");
      noPending.classList.remove("hidden");
      return;
    }

    pendingList.parentElement.parentElement.classList.remove("hidden");
    noPending.classList.add("hidden");

    // Sort conversations by waiting time (most recent first)
    conversations.sort((a, b) => {
      return new Date(b.waiting_since) - new Date(a.waiting_since);
    });

    // Clear existing list
    pendingList.innerHTML = "";

    // Add each conversation to the table
    conversations.forEach((conversation) => {
      const waitingSince = new Date(conversation.waiting_since);
      const now = new Date();
      const waitingMinutes = Math.floor((now - waitingSince) / 60000);
      const waitingTime = formatTimeAgo(conversation.waiting_since);
      const tr = document.createElement("tr");

      // Use user info, default to placeholder if not available
      const userName = conversation.user_info?.name || "Unknown User";
      const userApexId = conversation.user_info?.apex_id || "N/A";
      const reason = conversation.reason || "General assistance";

      // Format time requested in Pacific Time (company timezone)
      const timeRequested = waitingSince.toLocaleString("en-US", {
        timeZone: "America/Los_Angeles",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        timeZoneName: "short",
      });

      // Also show UTC time for clarity
      const utcTime = waitingSince.toISOString().substr(11, 8) + " UTC";

      // Create tooltip with multiple timezones
      const easternTime = waitingSince.toLocaleString("en-US", {
        timeZone: "America/New_York",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        timeZoneName: "short",
      });
      const pacificTime = waitingSince.toLocaleString("en-US", {
        timeZone: "America/Los_Angeles",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        timeZoneName: "short",
      });
      const tooltipText = `UTC: ${utcTime} | ET: ${easternTime} | PT: ${pacificTime}`;

      // Calculate SLA status (4 minutes)
      let slaStatus = "";
      let slaClass = "";
      if (waitingMinutes < 3) {
        slaStatus = "Within SLA";
        slaClass = "bg-green-100 text-green-800";
      } else if (waitingMinutes < 4) {
        slaStatus = "Near SLA";
        slaClass = "bg-yellow-100 text-yellow-800";
      } else {
        const overSLA = waitingMinutes - 4;
        slaStatus = `${overSLA} min over SLA`;
        slaClass = "bg-red-100 text-red-800";
      }

      tr.innerHTML = `
                <td class="sticky left-0 z-10 bg-white px-3 py-4 whitespace-nowrap">
                    <div class="text-sm font-medium text-gray-900">${userName}</div>
                    <div class="text-xs text-gray-500 sm:hidden">${userApexId}</div>
                </td>
                <td class="px-3 py-4 whitespace-nowrap hidden sm:table-cell">
                    <div class="text-sm text-gray-500">${userApexId}</div>
                </td>
                <td class="px-3 py-4">
                    <div class="text-sm text-gray-700 max-w-xs truncate">${reason}</div>
                </td>
                <td class="px-3 py-4 whitespace-nowrap hidden lg:table-cell">
                    <div class="text-sm text-gray-500 timezone-tooltip" data-tooltip="${tooltipText}">${timeRequested}</div>
                    <div class="text-xs text-gray-400">${utcTime}</div>
                </td>
                <td class="px-3 py-4 whitespace-nowrap hidden md:table-cell">
                    <div class="text-sm text-gray-500">${waitingTime}</div>
                </td>
                <td class="px-3 py-4 whitespace-nowrap hidden xl:table-cell">
                    <span class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full ${slaClass}">
                        ${slaStatus}
                    </span>
                </td>
                <td class="px-3 py-4 whitespace-nowrap hidden sm:table-cell">
                    <span class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full bg-yellow-100 text-yellow-800">
                        <span class="status-indicator status-waiting"></span>
                        Waiting
                    </span>
                </td>
                <td class="sticky right-0 z-10 bg-white px-3 py-4 whitespace-nowrap text-center text-sm font-medium action-cell">
                    <a href="/agent/conversation/${conversation.id}" class="inline-flex items-center px-3 py-1.5 border border-transparent text-xs font-medium rounded text-white bg-indigo-600 hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500">
                        Join
                    </a>
                </td>
            `;

      pendingList.appendChild(tr);
    });
  }

  // Format ISO date to time ago (e.g., "5 minutes ago")
  function formatTimeAgo(isoDate) {
    const date = new Date(isoDate);
    const now = new Date();
    const seconds = Math.floor((now - date) / 1000);

    let interval = Math.floor(seconds / 31536000);
    if (interval >= 1) {
      return interval === 1 ? "1 year ago" : `${interval} years ago`;
    }

    interval = Math.floor(seconds / 2592000);
    if (interval >= 1) {
      return interval === 1 ? "1 month ago" : `${interval} months ago`;
    }

    interval = Math.floor(seconds / 86400);
    if (interval >= 1) {
      return interval === 1 ? "1 day ago" : `${interval} days ago`;
    }

    interval = Math.floor(seconds / 3600);
    if (interval >= 1) {
      return interval === 1 ? "1 hour ago" : `${interval} hours ago`;
    }

    interval = Math.floor(seconds / 60);
    if (interval >= 1) {
      return interval === 1 ? "1 minute ago" : `${interval} minutes ago`;
    }

    return seconds < 10 ? "just now" : `${seconds} seconds ago`;
  }

  // Update the "last updated" text
  function updateLastUpdated() {
    const now = new Date();
    const timeString = now.toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
      timeZoneName: "short",
    });
    lastUpdated.textContent = `Last updated: ${timeString}`;
  }

  // Clean up on page unload
  window.addEventListener("beforeunload", function () {
    clearInterval(refreshInterval);
    clearInterval(callbackRefreshInterval);
  });

  // ============================================================================
  // CALLBACK MANAGEMENT FUNCTIONALITY
  // ============================================================================

  // Callback elements
  const callbacksList = document.getElementById("callbacks-list");
  const noCallbacks = document.getElementById("no-callbacks");
  const callbacksLastUpdated = document.getElementById(
    "callbacks-last-updated",
  );
  const completeModal = document.getElementById("complete-modal");
  const callbackNotes = document.getElementById("callback-notes");
  const cancelComplete = document.getElementById("cancel-complete");
  const confirmComplete = document.getElementById("confirm-complete");
  const aiAssistBtn = document.getElementById("ai-assist-btn");

  let currentCallbackId = null;

  // Initialize callbacks
  fetchPendingCallbacks();

  // Set up auto-refresh for callbacks every 30 seconds
  const callbackRefreshInterval = setInterval(fetchPendingCallbacks, 30000);

  // Modal event listeners
  if (cancelComplete)
    cancelComplete.addEventListener("click", hideCompleteModal);
  if (confirmComplete)
    confirmComplete.addEventListener("click", confirmCallbackComplete);
  if (aiAssistBtn) aiAssistBtn.addEventListener("click", handleAIAssist);

  // Close modal when clicking outside
  if (completeModal) {
    completeModal.addEventListener("click", function (e) {
      if (e.target === completeModal) {
        hideCompleteModal();
      }
    });
  }

  // Fetch pending callbacks from the API
  async function fetchPendingCallbacks() {
    try {
      const response = await fetch("/api/callbacks/pending");
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const result = await response.json();
      if (result.success) {
        renderCallbacks(result.callbacks, result);
      } else {
        throw new Error(result.error || "Failed to fetch callbacks");
      }
      updateCallbacksLastUpdated();

      return result.callbacks;
    } catch (error) {
      console.error("Error fetching callbacks:", error);
      if (callbacksList) {
        callbacksList.innerHTML = `
                    <tr>
                        <td colspan="7" class="px-6 py-4 text-sm text-red-500 text-center">
                            Error loading callback requests. Please try again.
                        </td>
                    </tr>
                `;
      }
    }
  }

  // Render callbacks in the table
  function renderCallbacks(callbacks, result) {
    if (!callbacksList) return;

    // Check for warnings (e.g., Azure Storage not configured)
    if (result && result.warning) {
      callbacksList.innerHTML = `
                <tr>
                    <td colspan="7" class="px-6 py-4 text-sm text-amber-600 text-center">
                        <div class="flex items-center justify-center">
                            <svg class="w-5 h-5 mr-2" fill="currentColor" viewBox="0 0 20 20">
                                <path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/>
                            </svg>
                            ${result.warning}
                        </div>
                    </td>
                </tr>
            `;
      callbacksList.parentElement.parentElement.classList.remove("hidden");
      if (noCallbacks) noCallbacks.classList.add("hidden");
      return;
    }

    if (callbacks.length === 0) {
      callbacksList.innerHTML = "";
      callbacksList.parentElement.parentElement.classList.add("hidden");
      if (noCallbacks) noCallbacks.classList.remove("hidden");
      return;
    }

    callbacksList.parentElement.parentElement.classList.remove("hidden");
    if (noCallbacks) noCallbacks.classList.add("hidden");

    // Sort callbacks by creation time (most recent first)
    callbacks.sort((a, b) => {
      return new Date(b.created_at) - new Date(a.created_at);
    });

    // Clear existing list
    callbacksList.innerHTML = "";

    // Add each callback to the table
    callbacks.forEach((callback) => {
      const createdAt = formatTimeAgo(callback.created_at);
      const tr = document.createElement("tr");

      // Format status
      let statusBadge = "";
      switch (callback.status) {
        case "pending":
          statusBadge =
            '<span class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full bg-yellow-100 text-yellow-800">Pending</span>';
          break;
        case "pending_user_info":
          statusBadge =
            '<span class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full bg-blue-100 text-blue-800">Collecting Info</span>';
          break;
        case "completed":
          statusBadge =
            '<span class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full bg-green-100 text-green-800">Completed</span>';
          break;
        default:
          statusBadge =
            '<span class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full bg-gray-100 text-gray-800">Unknown</span>';
      }

      tr.innerHTML = `
                <td class="px-6 py-4 whitespace-nowrap">
                    <div class="text-sm font-medium text-gray-900">${callback.user_name || "Unknown"}</div>
                    <div class="text-sm text-gray-500">ID: ${callback.apex_id || "N/A"}</div>
                </td>
                <td class="px-6 py-4 whitespace-nowrap hidden sm:table-cell">
                    <div class="text-sm text-gray-900">${callback.phone_number || "Not provided"}</div>
                </td>
                <td class="px-6 py-4 whitespace-nowrap hidden md:table-cell">
                    <div class="text-sm text-gray-900">${callback.best_time || "Not specified"}</div>
                </td>
                <td class="px-6 py-4">
                    <div class="text-sm text-gray-900">${callback.reason || "General assistance"}</div>
                </td>
                <td class="px-6 py-4 whitespace-nowrap hidden lg:table-cell">
                    <div class="text-sm text-gray-500">${createdAt}</div>
                </td>
                <td class="px-6 py-4 whitespace-nowrap hidden sm:table-cell">
                    ${statusBadge}
                </td>
                <td class="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                    ${
                      callback.status === "pending" && callback.phone_number
                        ? `<button onclick="showCompleteModal('${callback.callback_id}')" class="text-green-600 hover:text-green-900">Complete</button>`
                        : '<span class="text-gray-400">-</span>'
                    }
                </td>
            `;

      callbacksList.appendChild(tr);
    });
  }

  // Update the callbacks "last updated" text
  function updateCallbacksLastUpdated() {
    if (callbacksLastUpdated) {
      const now = new Date();
      const timeString = now.toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
      });
      callbacksLastUpdated.textContent = `Last updated: ${timeString}`;
    }
  }

  // Show complete callback modal
  window.showCompleteModal = function (callbackId) {
    currentCallbackId = callbackId;
    if (callbackNotes) callbackNotes.value = "";
    if (completeModal) completeModal.classList.remove("hidden");
  };

  // Hide complete callback modal
  function hideCompleteModal() {
    currentCallbackId = null;
    if (callbackNotes) callbackNotes.value = "";
    if (completeModal) completeModal.classList.add("hidden");
  }

  // Handle AI assist button click
  async function handleAIAssist() {
    if (!currentCallbackId || !aiAssistBtn) return;

    const originalText = aiAssistBtn.innerHTML;
    aiAssistBtn.disabled = true;
    aiAssistBtn.innerHTML = "Generating summary...";

    try {
      // Find the callback in our list to get details
      const callbacks = await fetchPendingCallbacks();
      const callback = callbacks.find(
        (cb) => cb.callback_id === currentCallbackId,
      );

      if (!callback) {
        throw new Error("Callback not found");
      }

      // Call AI summarization API
      const response = await fetch("/api/callbacks/ai-summarize", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          callback_info: callback,
        }),
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const result = await response.json();
      if (result.success && result.summary) {
        // Set the AI-generated summary in the textarea
        if (callbackNotes) callbackNotes.value = result.summary;

        // Show a hint if it's a template
        if (result.is_template) {
          console.log("Using template summary (AI not configured)");
        }
      } else {
        throw new Error(result.error || "Failed to generate summary");
      }
    } catch (error) {
      console.error("Error generating AI summary:", error);
      alert("Unable to generate summary. Please write your notes manually.");
    } finally {
      aiAssistBtn.disabled = false;
      aiAssistBtn.innerHTML = originalText;
    }
  }

  // Confirm callback completion
  async function confirmCallbackComplete() {
    if (!currentCallbackId || !confirmComplete) return;

    const notes = callbackNotes ? callbackNotes.value.trim() : "";

    try {
      confirmComplete.disabled = true;
      confirmComplete.innerHTML = "Completing...";

      const response = await fetch(
        `/api/callbacks/${currentCallbackId}/complete`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ notes }),
        },
      );

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const result = await response.json();
      if (result.success) {
        hideCompleteModal();
        fetchPendingCallbacks(); // Refresh the list
      } else {
        throw new Error(result.error || "Failed to complete callback");
      }
    } catch (error) {
      console.error("Error completing callback:", error);
      alert("Error completing callback: " + error.message);
    } finally {
      confirmComplete.disabled = false;
      confirmComplete.innerHTML = "Complete Callback";
    }
  }
});

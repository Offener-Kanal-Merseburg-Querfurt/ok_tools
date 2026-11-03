(function ($) {
  $(function () {
    var $modal = $('#dayPlanModal');
    var plannedItems = [];
    // Local midnight, not UTC: across the DST switch a UTC date shifted by
    // whole days lands on the previous evening and toISOString() then names
    // the Sunday before the intended Monday.
    var calendarStartDate = INITIAL_CALENDAR_START ? new Date(INITIAL_CALENDAR_START + 'T00:00:00') : null;

    function formatLocalDate(date) {
      return date.getFullYear() + '-' + String(date.getMonth() + 1).padStart(2, '0')
        + '-' + String(date.getDate()).padStart(2, '0');
    }

    function announce(message) {
      $('#planningA11yLive').text(message || '');
    }

    function showToast(message, type) {
      var cssClass = 'planning-toast';
      if (type === 'error') cssClass += ' planning-toast--error';
      if (type === 'success') cssClass += ' planning-toast--success';

      var $toast = $('<div class="' + cssClass + '"></div>').text(message || '');
      $('#planningToastRegion').append($toast);
      setTimeout(function () {
        $toast.fadeOut(250, function () { $(this).remove(); });
      }, 3200);
    }

    function notify(message, type) {
      showToast(message, type || 'info');
      announce(message);
    }

    function showInlineNotice(message) {
      var $notice = $('#planningInlineNotice');
      $notice.text(message || '').prop('hidden', !message);
    }

    function clearInlineNotice() {
      $('#planningInlineNotice').text('').prop('hidden', true);
    }

    function debounce(fn, wait) {
      var timeoutId = null;
      return function () {
        var args = arguments;
        clearTimeout(timeoutId);
        timeoutId = setTimeout(function () {
          fn.apply(null, args);
        }, wait || 150);
      };
    }

    function openActionModal(options) {
      return new Promise(function (resolve) {
        var modalEl = document.getElementById('planningActionModal');
        if (!modalEl || !window.bootstrap || !bootstrap.Modal) {
          resolve(null);
          return;
        }

        var opts = options || {};
        var $message = $('#planningActionMessage');
        var $input = $('#planningActionInput');
        var $inputLabel = $('#planningActionInputLabel');
        var $confirmBtn = $('#planningActionConfirmBtn');

        $('#planningActionLabel').text(opts.title || gettext('Confirm action'));
        $message.text(opts.message || '');

        if (opts.withInput) {
          // Set input type (text or date)
          var inputType = opts.inputType || 'text';
          $input.attr('type', inputType);
          
          if (inputType === 'date') {
            // For date inputs, don't use placeholder (not supported in all browsers)
            $input.prop('hidden', false).val(opts.initialValue || '');
          } else {
            $input.prop('hidden', false).val(opts.initialValue || '').attr('placeholder', opts.placeholder || '');
          }
          $inputLabel.prop('hidden', false).text(opts.inputLabel || gettext('Enter value'));
        } else {
          $input.prop('hidden', true).val('');
          $inputLabel.prop('hidden', true);
        }

        $confirmBtn.text(opts.confirmText || gettext('Confirm'));

        var actionModal = new bootstrap.Modal(modalEl);
        var settled = false;

        function finish(value) {
          if (settled) return;
          settled = true;
          resolve(value);
        }

        $confirmBtn.off('click.planningAction').on('click.planningAction', function () {
          var value = opts.withInput ? ($input.val() || '').trim() : true;
          finish(value);
          actionModal.hide();
        });

        $(modalEl).off('hidden.bs.modal.planningAction').on('hidden.bs.modal.planningAction', function () {
          if (!settled) {
            finish(null);
          }
          $confirmBtn.off('click.planningAction');
        });

        actionModal.show();
      });
    }
    
    // Parse broadcast block from settings
    const [startH, startM] = BROADCAST_START.split(':').map(Number);
    const [endH, endM] = BROADCAST_END.split(':').map(Number);
    const blockStart = startH * 3600 + startM * 60; // seconds
    const blockEnd = endH * 3600 + endM * 60; // seconds
    const maxBlockSeconds = blockEnd - blockStart;

    // Normalize duration: if value is less than 3600 (1 hour), it might be in minutes (old data)
    // Convert to seconds if needed
    // NOTE: This function is only used for formatTime() to handle old data format.
    // When loading from API, duration is always in seconds and should NOT be normalized.
    function normalizeDuration(duration) {
      // If duration is less than 3600 seconds (1 hour), it might be stored in minutes
      // But we need to be more careful - short videos (1-2 minutes) are valid in seconds
      // Only convert if the value is suspiciously small for a video (less than 30 seconds)
      // and could reasonably be minutes (e.g., 5 minutes = 5, which would be 5 seconds if in seconds)
      if (duration < 3600 && duration > 0) {
        // If duration is less than 30, it's likely minutes (old format)
        // Videos shorter than 30 seconds are very rare, so this is a safe threshold
        if (duration < 30) {
          return duration * 60; // Convert minutes to seconds
        }
        // For 30-3600 seconds, assume it's already in seconds (could be 30s to 1h video)
      }
      return duration; // Already in seconds
    }

    // Format seconds to MM:SS (with normalization for old data format)
    function formatTime(seconds) {
      const normalized = normalizeDuration(seconds);
      const mins = Math.floor(normalized / 60);
      const secs = normalized % 60;
      return mins + ':' + secs.toString().padStart(2, '0');
    }

    // Format seconds to MM:SS (without normalization - for time calculations)
    function formatTimeOnly(seconds) {
      const mins = Math.floor(seconds / 60);
      const secs = seconds % 60;
      return mins + ':' + secs.toString().padStart(2, '0');
    }

    // Convert time string HH:MM or HH:MM:SS to seconds
    function timeToSeconds(timeStr) {
      if (!timeStr) return 0;
      const parts = timeStr.split(":");
      const h = parseInt(parts[0], 10) || 0;
      const m = parseInt(parts[1], 10) || 0;
      const s = parseInt(parts[2], 10) || 0;
      return h * 3600 + m * 60 + s;
    }

    // Convert seconds to HH:MM:SS format
    function secondsToTimeString(seconds) {
      const days = Math.floor(seconds / 86400);
      const h = Math.floor((seconds % 86400) / 3600);
      const m = Math.floor((seconds % 3600) / 60);
      const s = seconds % 60;
      return h.toString().padStart(2, '0') + ':' + m.toString().padStart(2, '0') + ':' + s.toString().padStart(2, '0');
    }

    // Get day offset from seconds (0 = same day, 1 = next day, etc.)
    function getDayOffset(seconds) {
      return Math.floor(seconds / 86400);
    }

    // Convert seconds to HH:MM format (for display without seconds)
    function secondsToTimeStringShort(seconds) {
      const h = Math.floor(seconds / 3600);
      const m = Math.floor((seconds % 3600) / 60);
      return h.toString().padStart(2, '0') + ':' + m.toString().padStart(2, '0');
    }

    // Check if time has seconds in second half of minute (30-59)
    // Accepts both HH:MM:SS and seconds (number)
    function isInSecondHalf(timeStrOrSeconds) {
      if (!timeStrOrSeconds) return false;
      let seconds = 0;
      if (typeof timeStrOrSeconds === 'number') {
        seconds = timeStrOrSeconds % 60;
      } else {
        const parts = timeStrOrSeconds.split(":");
        if (parts.length >= 3) {
          seconds = parseInt(parts[2], 10) || 0;
        }
      }
      return seconds >= 30 && seconds <= 59;
    }
    
    // Convert HH:MM:SS to HH:MM for display
    function timeToDisplay(timeStr) {
      if (!timeStr) return '';
      const parts = timeStr.split(":");
      if (parts.length >= 2) {
        return parts[0] + ':' + parts[1];
      }
      return timeStr;
    }
    
    // Convert HH:MM to HH:MM:SS (add seconds if missing)
    function timeWithSeconds(timeStr, defaultSeconds = 0) {
      if (!timeStr) return '';
      const parts = timeStr.split(":");
      if (parts.length === 2) {
        return timeStr + ':' + defaultSeconds.toString().padStart(2, '0');
      }
      return timeStr;
    }
    
    // Get internal time with seconds from input element
    function getInternalTime($input) {
      const internalTime = $input.data('internal-time');
      if (internalTime) {
        return internalTime;
      }
      // Fallback: if no internal time, use display time and add :00
      const displayTime = $input.val();
      return timeWithSeconds(displayTime, 0);
    }

    function setDesiredTime($input, displayTime) {
      if (displayTime && displayTime.match(/^\d{2}:\d{2}$/)) {
        $input.data('desired-time', displayTime);
      }
    }

    function getDesiredTime($input) {
      const stored = $input.data('desired-time');
      if (stored && stored.match(/^\d{2}:\d{2}$/)) {
        return stored;
      }
      const current = $input.val();
      if (current && current.match(/^\d{2}:\d{2}$/)) {
        return current;
      }
      return '00:00';
    }

    function normalizeDisplayTime(displayTime) {
      if (!displayTime) return null;
      const parts = displayTime.split(':');
      if (parts.length !== 2) return null;
      const h = parseInt(parts[0], 10);
      const m = parseInt(parts[1], 10);
      if (isNaN(h) || isNaN(m) || h < 0 || h > 23 || m < 0 || m > 59) {
        return null;
      }
      return h.toString().padStart(2, '0') + ':' + m.toString().padStart(2, '0');
    }

    // Youth protection: an age-rated item must fit entirely inside its allowed
    // window. Window and item may both cross midnight, so the check runs on a
    // circular clock, exactly like the server-side validation.
    function youthProtectionFits(yp, startSec, durationSec) {
      if (!yp) return true;
      const length = yp.window_length_seconds || 86400;
      const offset = ((startSec - (yp.window_start_seconds || 0)) % 86400 + 86400) % 86400;
      return offset + Math.max(durationSec || 0, 0) <= length;
    }

    function youthProtectionOf($row) {
      const raw = $row.data('youth-protection');
      return raw || null;
    }

    function recalculateSchedule() {
      let currentEndSec = blockStart;
      const ypBlocked = [];

      $('#licenseTable tbody tr:not(.gap-row)').each(function (idx) {
        const $row = $(this);
        const $input = $row.find('.start-time-input');
        const isManualTime = $input.data('manual-time') === true;
        
        let startSec;
        let startWithSeconds;
        
        if (isManualTime) {
          // Manual time mode: use the time exactly as set by user (STRICT MODE)
          // Do NOT recalculate or adjust the time
          const internalTime = getInternalTime($input);
          if (internalTime && internalTime.includes(':') && (internalTime.match(/:/g) || []).length === 2) {
            // Internal time already has seconds (HH:MM:SS format)
            startSec = timeToSeconds(internalTime);
            startWithSeconds = internalTime;
          } else {
            // Fallback to desired time (HH:MM format)
            const desiredDisplay = getDesiredTime($input);
            startSec = timeToSeconds(desiredDisplay + ':00');
            startWithSeconds = secondsToTimeString(startSec);
          }
        } else {
          // Auto mode: calculate based on previous video end time
          // But if internal-time is already set (e.g., from recalculateAllStartTimes), use it
          const internalTime = getInternalTime($input);
          if (internalTime && internalTime.includes(':') && (internalTime.match(/:/g) || []).length === 2) {
            // Internal time already set with seconds (HH:MM:SS format) - use it but ensure it's not before currentEndSec
            const internalSec = timeToSeconds(internalTime);
            startSec = Math.max(internalSec, currentEndSec);
            startWithSeconds = secondsToTimeString(startSec);
          } else {
            // Fallback to desired time calculation
            const desiredDisplay = getDesiredTime($input);
            const desiredSec = timeToSeconds(desiredDisplay + ':00');
            startSec = Math.max(desiredSec, currentEndSec);
            startWithSeconds = secondsToTimeString(startSec);
          }
        }

        $input.data('internal-time', startWithSeconds);
        $row.find('.time-with-seconds').text(startWithSeconds);

        // Visual indicators
        let bgColor = '';
        let title = '';
        
        if (isManualTime) {
          // Manual time mode indicator
          bgColor = '#e7f3ff';
          title = gettext('Manual time setting (can be outside block)');
        } else if (isInSecondHalf(startSec)) {
          bgColor = '#fff3cd';
          title = gettext('Video starts in second half of minute (30-59 seconds)');
        }
        
        // Check if outside block
        if (startSec < blockStart || startSec >= blockEnd) {
          if (bgColor) {
            bgColor = '#ffe7e7'; // Light red for outside block
          } else {
            bgColor = '#ffe7e7';
          }
          if (title) {
            title += ' • ' + gettext('Outside broadcast block');
          } else {
            title = gettext('Outside broadcast block');
          }
        }
        
        const duration0 = plannedItems[idx] ? plannedItems[idx].duration : (function () {
          const durationText = $row.find('td').eq(5).text();
          if (!durationText) return 0;
          const parts = durationText.split(':').map(Number);
          if (parts.length === 2) return parts[0] * 60 + parts[1];
          return 0;
        })();
        const yp = youthProtectionOf($row);
        const ypViolated = !youthProtectionFits(yp, startSec, duration0);
        if (ypViolated) {
          bgColor = '#ffd4d4';
          const ypText = gettext('Youth protection: broadcast only allowed between')
            + ' ' + yp.allowed_from + ' – ' + yp.allowed_until + ' (' + yp.label + ')';
          title = title ? title + ' • ' + ypText : ypText;
        }
        $row.toggleClass('yp-violation', ypViolated);
        if (ypViolated) {
          ypBlocked.push(
            $row.data('license-number') + ' (' + yp.label + ': '
            + yp.allowed_from + '–' + yp.allowed_until + ')');
        }

        $input.css('background-color', bgColor).attr('title', title);

        const duration = plannedItems[idx] ? plannedItems[idx].duration : (function () {
          const durationText = $row.find('td').eq(5).text();
          if (!durationText) return 0;
          const parts = durationText.split(':').map(Number);
          if (parts.length === 2) {
            return parts[0] * 60 + parts[1]; // Already in seconds from MM:SS format
          }
          return 0;
        })();

        const endSec = startSec + duration;
        const endTimeString = secondsToTimeString(endSec);
        const endDayOffset = getDayOffset(endSec);
        
        // Update end time display with day offset if needed
        let endTimeHTML = endTimeString;
        if (endDayOffset > 0) {
          endTimeHTML = endTimeString + '<br><small style="display: block; font-size: 11px; color: #6c757d; font-weight: normal;">(+' + endDayOffset + ' ' + gettext('day') + ')</small>';
        }
        $row.find('.end-time').html(endTimeHTML);

        if (plannedItems[idx]) {
          plannedItems[idx].start = startWithSeconds;
        }

        // Update currentEndSec to track the latest end time
        // (used for positioning next auto-mode videos)
        currentEndSec = Math.max(currentEndSec, endSec);
      });

      // Saving is refused server-side for these, so say why while there is
      // still time to move the item.
      if (ypBlocked.length > 0) {
        showInlineNotice(
          gettext('Youth protection: these items may not be broadcast at the '
                  + 'planned time and the day cannot be saved:')
          + ' ' + ypBlocked.join(', '));
      }

      updateRemainingTime();
    }

    // Round time to nearest 0 or 5 minutes
    // If within 45 seconds after a 0/5 mark, round down to that mark
    // Otherwise round up to next 0/5 mark
    function roundToFiveMinutes(seconds) {
      const totalMinutes = Math.floor(seconds / 60);
      const remainderSeconds = seconds % 60;
      
      // Check if current minute is a 0 or 5 mark
      const isAtFiveMinuteMark = (totalMinutes % 5 === 0);
      
      // If we're at 0 or 5 minute mark and within 45 seconds
      if (isAtFiveMinuteMark && remainderSeconds <= 45) {
        // Round down to this mark (ignore the seconds)
        return totalMinutes * 60;
      }
      
      // Otherwise round UP to next 5-minute mark
      const nextFiveMinuteMark = Math.ceil((totalMinutes + 1) / 5) * 5;
      return nextFiveMinuteMark * 60;
    }

    function alignToFiveMinutesKeepingSeconds(seconds) {
      const remainderSeconds = seconds % 60;
      const totalMinutes = Math.floor(seconds / 60);
      let alignedMinutes = totalMinutes;

      if (alignedMinutes % 5 !== 0) {
        alignedMinutes = Math.ceil(alignedMinutes / 5) * 5;
      }

      let aligned = alignedMinutes * 60 + remainderSeconds;
      if (aligned < seconds) {
        aligned += 300;
      }

      return aligned;
    }

    // Calculate end time for display (with seconds and day offset if needed)
    function calculateEndTime(startTime, durationSeconds) {
      const startSec = timeToSeconds(startTime);
      const endSec = startSec + durationSeconds;
      const endTimeString = secondsToTimeString(endSec);
      const endDayOffset = getDayOffset(endSec);
      
      if (endDayOffset > 0) {
        return endTimeString + '<br><small style="display: block; font-size: 11px; color: #6c757d; font-weight: normal;">(+' + endDayOffset + ' ' + gettext('day') + ')</small>';
      }
      return endTimeString;
    }

    // Display block duration on page load
    $('#blockDurationDisplay').text(formatTime(maxBlockSeconds));

    function renderValidationErrors(xhr, fallbackMessage) {
      var payload = xhr && xhr.responseJSON ? xhr.responseJSON : null;
      if (payload && payload.errors && Array.isArray(payload.errors) && payload.errors.length > 0) {
        var details = payload.errors.map(function (item) {
          return '- ' + (item.field || 'unknown') + ': ' + item.message;
        }).join('\n');
        showInlineNotice((payload.error || gettext('Validation failed')) + ' • ' + details.replace(/\n/g, ' '));
        notify(payload.error || gettext('Validation failed'), 'error');
        return;
      }
      showInlineNotice(fallbackMessage);
      notify(fallbackMessage, 'error');
    }

    function loadTemplates() {
      $.get('/api/planning/templates/', function (data) {
        var $select = $('#templateSelect');
        $select.find('option:not(:first)').remove();
        (data.templates || []).forEach(function (tpl) {
          $select.append('<option value="' + tpl.id + '">' + tpl.name + '</option>');
        });
      });
    }

    // Load weekly statistics on page load
    // (function will be called after it's defined below)

    function openDayModal($trigger) {
          clearInlineNotice();
          $('.date-cell').removeClass('selected-day').attr('aria-selected', 'false');
          $trigger.addClass('selected-day').attr('aria-selected', 'true');
          const iso = $trigger.data('date');
          // Creating date from ISO format with UTC parsing to prevent timezone issues
          const jsDate = new Date(iso + 'T00:00:00Z');

          $('#modalDateDisplay').text(jsDate.toLocaleDateString('de-DE'));
          $('#modalWeekday').text(
              jsDate.toLocaleDateString('de-DE', { weekday: 'long' })
          );
          $('#dayPlanModal').data('isoDate', iso);

          // clear old data
          plannedItems = [];
          $('#licenseTable tbody').empty();
          $('#noteText').val('');
          updateRemainingTime();

          // --- load saved TagesPlan if exists ---
          $.get('/api/day-plan/' + iso + '/')
            .done(function (data) {
                // restore rows
                data.items.forEach(function (item) {
                    // Duration from API is already in seconds (from License/VideoFile)
                    // Don't normalize it, as API always returns correct duration in seconds
                    const durationSeconds = item.duration || 0;
                    const endTime = calculateEndTime(item.start, durationSeconds);
                    const licenseId = item.license_id || '';
                    const licenseLink = licenseId ? '<a href="/admin/licenses/license/' + licenseId + '/change/" target="_blank">' + item.number + '</a>' : item.number;
                    const contributionLink = licenseId ? ' <a href="/admin/contributions/contribution/?q=' + item.number + '" target="_blank" title="' + gettext('View Contributions') + '">📺</a>' : '';
                    const senderResponsible = item.sender_responsible || item.author || '';
                    // Store time with seconds internally, but display only HH:MM
                    let startTimeWithSeconds = item.start;
                    if (startTimeWithSeconds && (!startTimeWithSeconds.includes(':') || (startTimeWithSeconds.match(/:/g) || []).length === 1)) {
                      // Convert HH:MM to HH:MM:SS
                      const [h, m] = startTimeWithSeconds.split(":").map(Number);
                      startTimeWithSeconds = h.toString().padStart(2, '0') + ':' + m.toString().padStart(2, '0') + ':00';
                    }
                    const startTimeDisplay = timeToDisplay(startTimeWithSeconds); // Show only HH:MM
                    const isLive = Boolean(item.is_live);
                    const liveBadge = isLive ? '<span class="live-badge" style="margin-left: 4px;"><svg viewBox="0 0 24 24" fill="#dc3545" stroke="#dc3545" stroke-width="2" width="14" height="14" aria-hidden="true"><circle cx="12" cy="12" r="10"></circle><path d="M12 8v4l3 3" fill="white" stroke="white" stroke-width="1.5"></path></svg></span>' : '';
                    const $row = $('<tr data-license-id="' + (licenseId || '') + '" data-license-number="' + item.number + '">' +
                      '<td><input type="time" class="form-control input-sm start-time-input" value="' + startTimeDisplay + '" data-internal-time="' + startTimeWithSeconds + '"><small class="time-with-seconds" style="display: block; font-size: 11px; color: #6c757d; font-weight: normal; margin-top: 2px;">' + startTimeWithSeconds + '</small></td>' +
                      '<td class="end-time">' + endTime + '</td>' +
                      '<td>' + licenseLink + contributionLink + liveBadge + '</td>' +
                      '<td>' + (item.title || '') + (item.subtitle ? ' – ' + item.subtitle : '') + '</td>' +
                      '<td class="sender-responsible">' + senderResponsible + '</td>' +
                      '<td>' + formatTime(durationSeconds) + '</td>' +
                      '<td><span class="drag-handle" style="cursor:move;font-size:18px;margin-right:6px;">&#9776;</span><button class="btn btn-xs btn-danger remove-row">&times;</button></td>' +
                      '</tr>');
                    $row.data('is-live', isLive);
                    $row.data('youth-protection', item.youth_protection || null);
                    $('#licenseTable tbody').append($row);

                    const $input = $row.find('.start-time-input');
                    setDesiredTime($input, startTimeDisplay);
                    $input.data('internal-time', startTimeWithSeconds);
                    // Check if time is outside block - if so, mark as manual
                    const startSec = timeToSeconds(startTimeWithSeconds);
                    if (startSec < blockStart || startSec >= blockEnd) {
                      $input.data('manual-time', true);
                    } else {
                      $input.data('manual-time', false);
                    }
                    $row.find('.time-with-seconds').text(startTimeWithSeconds);

                    // Apply visual indicator if time is in second half of minute (check internal seconds)
                    // Note: startSec is already defined above, so we reuse it
                    if (isInSecondHalf(startSec)) {
                      $row.find('.start-time-input').css('background-color', '#fff3cd').attr('title', gettext('Video starts in second half of minute (30-59 seconds)'));
                    }
                    plannedItems.push({
                      number: item.number,
                      duration: durationSeconds,
                      title: item.title,
                      subtitle: item.subtitle,
                      sender_responsible: senderResponsible,
                      license_id: licenseId,
                      start: startTimeWithSeconds,
                      is_live: isLive
                    });
                });

                recalculateSchedule();

                $('#noteText').val(data.comment || '');
                updateRemainingTime();
            })
            .fail(function () {
                // 404 - means no plan exists yet, leave modal empty
            });

          const modal = new bootstrap.Modal(document.getElementById('dayPlanModal'));
          modal.show();
      }

    $(document).on('click', '.date-cell', function () {
      openDayModal($(this));
    });

    function updateRemainingTime() {
      var videoItems = [];
      var gapRows = []; // Store gap rows to remove/update them

      // Собираем все видео с временем начала и длительностью
      $('#licenseTable tbody tr').each(function () {
        const $row = $(this);
        if ($row.hasClass('gap-row')) {
          gapRows.push($row);
          return; // skip gap rows
        }
        
        const $input = $row.find('.start-time-input');
        const startStr = getInternalTime($input);
        const durationText = $row.find('td').eq(5).text(); // MM:SS format (Duration is now column 5)
        const [mins, secs] = durationText.split(':').map(Number);
        const duration = mins * 60 + secs; // Already in seconds from MM:SS format
        
        if (startStr && duration) {
          const startSec = timeToSeconds(startStr);
          const endSec = startSec + duration;
          
          // Update end time display with day offset if needed
          const endTimeString = secondsToTimeString(endSec);
          const endDayOffset = getDayOffset(endSec);
          let endTimeHTML = endTimeString;
          if (endDayOffset > 0) {
            endTimeHTML = endTimeString + '<br><small style="display: block; font-size: 11px; color: #6c757d; font-weight: normal;">(+' + endDayOffset + ' ' + gettext('day') + ')</small>';
          }
          $row.find('.end-time').html(endTimeHTML);
          
          videoItems.push({
            start: startSec,
            end: endSec,
            duration: duration,
            $row: $row
          });
        }
      });

      // Remove old gap rows
      gapRows.forEach(function($row) {
        $row.remove();
      });

      if (videoItems.length === 0) {
        // No videos, full block is free
        const remaining = maxBlockSeconds;
        $('#remainingTime').removeClass('text-danger').addClass('text-success')
          .text(gettext('Full available'));
        updateModalSummary();
        return;
      }

      // Sort by start time
      videoItems.sort(function(a, b) {
        return a.start - b.start;
      });

      // Calculate total used time and insert gap visualization
      var totalUsedTime = 0;
      var currentPos = blockStart; // start from block beginning
      var outsideBlockCount = 0; // Count videos outside block
      var previousEnd = 0; // Track previous video end for gap display

      for (var i = 0; i < videoItems.length; i++) {
        var item = videoItems[i];
        
        // Check if video is completely outside broadcast block
        if (item.end <= blockStart || item.start >= blockEnd) {
          // Video is completely outside the block
          outsideBlockCount++;
          
          // Show gap between previous video and this one (if any)
          if (i > 0 && item.start > previousEnd) {
            var gapDuration = item.start - previousEnd;
            var gapMins = Math.floor(gapDuration / 60);
            var gapSecs = gapDuration % 60;
            var gapFormatted = gapMins + ':' + gapSecs.toString().padStart(2, '0');
            
            var gapClass = gapDuration >= 300 ? 'gap-row-large' : 'gap-row-small';
            var gapLabel = gapDuration >= 300 ? '⬇ ' + gettext('Large gap') : '⬇ ' + gettext('Gap');
            var gapSuffix = gapDuration >= 300 ? ' ' + gettext('free (can add video)') : ' ' + gettext('free');
            
            var gapRow = '<tr class="gap-row ' + gapClass + '">' +
              '<td colspan="2" style="text-align:center; font-weight: bold;">' + gapLabel + '</td>' +
              '<td colspan="5" style="text-align:center;">' + gapFormatted + gapSuffix + '</td>' +
              '<td></td>' +
              '</tr>';
            
            item.$row.before(gapRow);
          }
          
          previousEnd = item.end;
          continue;
        }

        // Show gap between previous video and this one (if any)
        // Only show if there was a previous event (previousEnd > 0)
        if (previousEnd > 0 && item.start > previousEnd) {
          var gapDuration = item.start - previousEnd;
          var gapMins = Math.floor(gapDuration / 60);
          var gapSecs = gapDuration % 60;
          var gapFormatted = gapMins + ':' + gapSecs.toString().padStart(2, '0');
          
          var gapClass = gapDuration >= 300 ? 'gap-row-large' : 'gap-row-small';
          var gapLabel = gapDuration >= 300 ? '⬇ ' + gettext('Large gap') : '⬇ ' + gettext('Gap');
          var gapSuffix = gapDuration >= 300 ? ' ' + gettext('free (can add video)') : ' ' + gettext('free');
          
          var gapRow = '<tr class="gap-row ' + gapClass + '">' +
            '<td colspan="2" style="text-align:center; font-weight: bold;">' + gapLabel + '</td>' +
            '<td colspan="5" style="text-align:center;">' + gapFormatted + gapSuffix + '</td>' +
            '<td></td>' +
            '</tr>';
          
          item.$row.before(gapRow);
        }

        // Clamp video to block boundaries (video may partially overlap)
        var videoStart = Math.max(item.start, blockStart);
        var videoEnd = Math.min(item.end, blockEnd);
        var videoInBlockDuration = videoEnd - videoStart;

        // Add video time (only the part within block)
        totalUsedTime += videoInBlockDuration;
        currentPos = videoEnd;
        previousEnd = item.end;
      }

      // Check if any video extends beyond the block
      var hasVideoExtendingBeyondBlock = false;
      for (var i = 0; i < videoItems.length; i++) {
        if (videoItems[i].end > blockEnd && videoItems[i].start < blockEnd) {
          hasVideoExtendingBeyondBlock = true;
          break;
        }
      }

      // Check if there are any large gaps (≥5 minutes)
      var hasLargeGaps = false;
      var currentPos = blockStart;
      for (var i = 0; i < videoItems.length; i++) {
        var item = videoItems[i];
        if (item.end <= blockStart || item.start >= blockEnd) {
          continue;
        }
        
        var videoStart = Math.max(item.start, blockStart);
        var gapDuration = videoStart - currentPos;
        
        if (gapDuration >= 300) { // gap >= 5 minutes
          hasLargeGaps = true;
          break;
        }
        
        currentPos = Math.max(currentPos, Math.min(item.end, blockEnd));
      }

      // Calculate remaining time
      var remaining = maxBlockSeconds - totalUsedTime;
      const $remaining = $('#remainingTime');
      
      // Build status message
      var statusText = '';
      var statusClass = 'text-success';
      
      // Block is full only if: video extends beyond AND no large gaps AND remaining < 5 min
      if (hasVideoExtendingBeyondBlock && !hasLargeGaps && remaining >= 0 && remaining < 300) {
        // Block is considered full
        statusText = gettext('Block filled (video extends beyond)');
        statusClass = 'text-success';
      } else if (remaining < 0) {
        statusText = gettext('Overplanned by %(time)s!').replace('%(time)s', formatTimeOnly(-remaining));
        statusClass = 'text-danger';
      } else {
        statusText = gettext('Still %(time)s free').replace('%(time)s', formatTimeOnly(remaining));
        statusClass = 'text-success';
      }
      
      // Add info about outside block broadcasts
      if (outsideBlockCount > 0) {
        statusText += ' • ' + gettext('%(count)s broadcast(s) outside block').replace('%(count)s', outsideBlockCount);
      }
      
      $remaining.removeClass('text-danger text-success').addClass(statusClass)
        .text(statusText);

      updateModalSummary();
    }

    function updateModalSummary() {
      var rows = $('#licenseTable tbody tr:not(.gap-row)');
      var outsideBlock = 0;
      var overlaps = 0;

      var ranges = [];
      rows.each(function () {
        var $row = $(this);
        var $input = $row.find('.start-time-input');
        var startSec = timeToSeconds(getInternalTime($input));
        var durationText = $row.find('td').eq(5).text();
        var parts = durationText.split(':').map(Number);
        var duration = (parts[0] || 0) * 60 + (parts[1] || 0);
        var endSec = startSec + duration;

        if (startSec < blockStart || startSec >= blockEnd) {
          outsideBlock += 1;
        }
        ranges.push({ start: startSec, end: endSec });
      });

      ranges.sort(function (a, b) { return a.start - b.start; });
      for (var i = 1; i < ranges.length; i++) {
        if (ranges[i].start < ranges[i - 1].end) {
          overlaps += 1;
        }
      }

      var largeGaps = $('#licenseTable tbody tr.gap-row-large').length;

      $('#summaryItems').text(gettext('Items') + ': ' + rows.length);
      $('#summaryOutside').text(gettext('Outside block') + ': ' + outsideBlock)
        .toggleClass('summary-chip--warning', outsideBlock > 0);
      $('#summaryLargeGaps').text(gettext('Large gaps') + ': ' + largeGaps)
        .toggleClass('summary-chip--warning', largeGaps > 0);
      $('#summaryOverlaps').text(gettext('Overlaps') + ': ' + overlaps)
        .toggleClass('summary-chip--danger', overlaps > 0);
    }

    // Check if position is free (no overlaps with existing videos)
    // Allow starting at rounded time if previous video ends within 45 seconds of that mark
    function isPositionFree(startSec, durationSec, videoItems) {
      const endSec = startSec + durationSec;
      
      for (var i = 0; i < videoItems.length; i++) {
        var item = videoItems[i];
        
        // Check if new video starts exactly at a 0 or 5 minute mark
        const startMinutes = Math.floor(startSec / 60);
        const startIsRounded = (startMinutes % 5 === 0) && (startSec % 60 === 0);
        
        // If starting at rounded time, allow if previous video ends within 45 seconds before this mark
        if (startIsRounded && item.end > startSec - 45 && item.end <= startSec) {
          // Previous video ends within 45 seconds before the rounded start time - OK
          continue;
        }
        
        // Check for overlap: new video starts before existing ends AND new video ends after existing starts
        if (startSec < item.end && endSec > item.start) {
          return false; // overlap detected
        }
      }
      return true;
    }

    // Find best position for new video (fill gaps or append to end)
    function findBestPosition(videoDuration) {
      var videoItems = [];
      
      // Collect all current videos
      $('#licenseTable tbody tr:not(.gap-row)').each(function () {
        const $row = $(this);
        const $input = $row.find('.start-time-input');
        const startStr = getInternalTime($input); // Get time with seconds
        const durationText = $row.find('td').eq(5).text(); // Duration column
        const [mins, secs] = durationText.split(':').map(Number);
        const duration = mins * 60 + secs; // Already in seconds from MM:SS format
        
        if (startStr && duration) {
          const startSec = timeToSeconds(startStr);
          videoItems.push({
            start: startSec,
            end: startSec + duration,
            duration: duration
          });
        }
      });

      // Sort by start time
      videoItems.sort(function(a, b) {
        return a.start - b.start;
      });

      // Try to find a gap that fits the video
      var currentPos = blockStart;
      
      for (var i = 0; i < videoItems.length; i++) {
        var item = videoItems[i];
        
        // Skip videos outside the block
        if (item.start >= blockEnd) break;
        if (item.end <= blockStart) continue;
        
        var videoStart = Math.max(item.start, blockStart);
        var gapDuration = videoStart - currentPos;
        
        // If there's a gap that fits our video (with some margin for rounding)
        if (gapDuration >= videoDuration) {
          // Try rounded position
          var roundedPos = roundToFiveMinutes(currentPos);
          
          // Check if rounded position is still free and fits in the gap
          if (roundedPos >= currentPos && 
              roundedPos + videoDuration <= videoStart && 
              isPositionFree(roundedPos, videoDuration, videoItems)) {
            return roundedPos;
          }
          
          // If rounded position doesn't work, use exact position if it fits
          if (currentPos + videoDuration <= videoStart) {
            return currentPos;
          }
        }
        
        currentPos = Math.max(currentPos, item.end);
      }
      
      // No suitable gap found, append to end
      // Round to 5 minutes, but make sure it doesn't overlap
      var roundedPos = roundToFiveMinutes(currentPos);
      
      // If rounding back would cause overlap, round forward instead
      if (roundedPos < currentPos || !isPositionFree(roundedPos, videoDuration, videoItems)) {
        // Round up to next 5-minute mark
        const totalMinutes = Math.ceil(currentPos / 60);
        const roundedMinutes = Math.ceil(totalMinutes / 5) * 5;
        roundedPos = roundedMinutes * 60;
      }
      
      return roundedPos;
    }

    $('#addLicenseBtn').on('click', function () {
      const number = $('#licenseNumberInput').val().trim();
      if (!number) return;

      $.get('/api/license/' + number + '/', function (data) {
        // Find best position for this video
        const bestPosition = findBestPosition(data.duration_seconds);
        const startTime = secondsToTimeString(bestPosition);
        const endTime = secondsToTimeString(bestPosition + data.duration_seconds);
        const licenseId = data.license_id || '';
        const licenseLink = licenseId ? '<a href="/admin/licenses/license/' + licenseId + '/change/" target="_blank">' + data.number + '</a>' : data.number;
                    const contributionLink = licenseId ? ' <a href="/admin/contributions/contribution/?q=' + data.number + '" target="_blank" title="' + gettext('View Contributions') + '">📺</a>' : '';
        const senderResponsible = data.sender_responsible || data.author || '';

        // Format start time: store with seconds internally, display only HH:MM
        // startTime is already HH:MM:SS from secondsToTimeString()
        const startTimeWithSeconds = startTime;
        const startTimeDisplay = timeToDisplay(startTimeWithSeconds); // Show only HH:MM
        const isLive = Boolean(data.is_live);
        const liveBadge = isLive ? '<span class="live-badge" style="margin-left: 4px;"><svg viewBox="0 0 24 24" fill="#dc3545" stroke="#dc3545" stroke-width="2" width="14" height="14" aria-hidden="true"><circle cx="12" cy="12" r="10"></circle><path d="M12 8v4l3 3" fill="white" stroke="white" stroke-width="1.5"></path></svg></span>' : '';
        const $row = $('<tr data-license-id="' + (licenseId || '') + '" data-license-number="' + data.number + '">' +
          '<td><input type="time" class="form-control input-sm start-time-input" value="' + startTimeDisplay + '" data-internal-time="' + startTimeWithSeconds + '"><small class="time-with-seconds" style="display: block; font-size: 11px; color: #6c757d; font-weight: normal; margin-top: 2px;">' + startTimeWithSeconds + '</small></td>' +
          '<td class="end-time">' + endTime + '</td>' +
          '<td>' + licenseLink + contributionLink + liveBadge + '</td>' +
          '<td>' + data.title + (data.subtitle ? ' – ' + data.subtitle : '') + '</td>' +
          '<td class="sender-responsible">' + senderResponsible + '</td>' +
          '<td>' + formatTime(data.duration_seconds) + '</td>' +
          '<td><span class="drag-handle" style="cursor:move;font-size:18px;margin-right:6px;">&#9776;</span><button class="btn btn-xs btn-danger remove-row">&times;</button></td>' +
          '</tr>');
        $row.data('is-live', isLive);
        $row.data('youth-protection', data.youth_protection || null);

        const $input = $row.find('.start-time-input');
        setDesiredTime($input, startTimeDisplay);
        $input.data('internal-time', startTimeWithSeconds);
        // New items are auto-positioned, not manual
        $input.data('manual-time', false);
        $row.find('.time-with-seconds').text(startTimeWithSeconds);

        // Find correct position to insert (sorted by time)
        var inserted = false;
        $('#licenseTable tbody tr:not(.gap-row)').each(function() {
          const $existingInput = $(this).find('.start-time-input');
          const existingStart = timeToSeconds(getInternalTime($existingInput));
          if (bestPosition < existingStart) {
            $(this).before($row);
            inserted = true;
            return false; // break
          }
        });
        
        if (!inserted) {
          $('#licenseTable tbody').append($row);
        }
        
        // Apply visual indicator if time is in second half of minute (check internal seconds)
        const startSec = timeToSeconds(startTimeWithSeconds);
        if (isInSecondHalf(startSec)) {
          $row.find('.start-time-input').css('background-color', '#fff3cd').attr('title', gettext('Video starts in second half of minute (30-59 seconds)'));
        }

        plannedItems.push({
          number: data.number,
          duration: data.duration_seconds,
          title: data.title,
          subtitle: data.subtitle,
          sender_responsible: senderResponsible,
          license_id: licenseId,
          start: startTime,
          is_live: isLive
        });

        // Sync planned items first to match DOM order before recalculating
        syncPlannedItemsFromTable();
        recalculateSchedule();
        updateRemainingTime();
        $('#licenseNumberInput').val('');
      }).fail(function () {
        notify(gettext('License not found or not confirmed'), 'error');
      });
    });

    // Get maximum allowed start time that doesn't cause overlaps
    // Returns object with {minStart, maxStart}
    function getAllowedStartTimeRange($input, currentNewStartSec) {
      const $currentRow = $input.closest('tr');
      const allRows = [];
      
      // Get current row's duration
      const currentDurationText = $currentRow.find('td').eq(5).text();
      const [currentMins, currentSecs] = currentDurationText.split(':').map(Number);
      const currentDuration = currentMins * 60 + currentSecs;
      
      // Collect all OTHER rows (excluding current row) with their start times and durations
      $('#licenseTable tbody tr:not(.gap-row)').each(function() {
        const $row = $(this);
        if ($row[0] === $currentRow[0]) {
          return; // Skip current row
        }
        
        const $rowInput = $row.find('.start-time-input');
        const startStr = getInternalTime($rowInput);
        if (!startStr) return;
        const startSec = timeToSeconds(startStr);
        
        const durationText = $row.find('td').eq(5).text();
        const [mins, secs] = durationText.split(':').map(Number);
        const duration = mins * 60 + secs;
        allRows.push({
          $row: $row,
          startSec: startSec,
          endSec: startSec + duration,
          duration: duration
        });
      });
      
      // Sort by start time
      allRows.sort(function(a, b) {
        return a.startSec - b.startSec;
      });
      
      // Find min start: maximum end time of all other videos (or block start if larger)
      let minStart = blockStart;
      for (let i = 0; i < allRows.length; i++) {
        if (allRows[i].endSec > minStart) {
          minStart = allRows[i].endSec;
        }
      }
      
      // Find max start: minimum start time of all other videos minus current duration
      // This ensures current video ends before any other video starts
      let maxStart = Infinity;
      for (let i = 0; i < allRows.length; i++) {
        const maxStartForThisItem = allRows[i].startSec - currentDuration;
        if (maxStartForThisItem < maxStart) {
          maxStart = maxStartForThisItem;
        }
      }
      
      return {
        minStart: minStart,
        maxStart: maxStart
      };
    }

    // Synchronize start time when input changes (just update)
    $('#licenseTable').on('input', '.start-time-input', function () {
      const $input = $(this);
      const normalized = normalizeDisplayTime($input.val());

      if (!normalized) {
        return; // wait until input is complete HH:MM
      }

      if ($input.val() !== normalized) {
        $input.val(normalized);
      }

      // Mark as manual time when user edits
      $input.data('manual-time', true);
      setDesiredTime($input, normalized);
      recalculateSchedule();
    });

    // Check if video overlaps with any other video
    function checkVideoOverlap($input, startSec, duration) {
      const $currentRow = $input.closest('tr');
      const endSec = startSec + duration;
      
      let hasOverlap = false;
      let conflictVideo = null;
      
      $('#licenseTable tbody tr:not(.gap-row)').each(function() {
        const $row = $(this);
        if ($row[0] === $currentRow[0]) {
          return; // Skip current row
        }
        
        const $rowInput = $row.find('.start-time-input');
        const rowStartStr = getInternalTime($rowInput);
        if (!rowStartStr) return;
        const rowStartSec = timeToSeconds(rowStartStr);
        
        const rowDurationText = $row.find('td').eq(5).text();
        const [mins, secs] = rowDurationText.split(':').map(Number);
        const rowDuration = mins * 60 + secs;
        const rowEndSec = rowStartSec + rowDuration;
        
        // Check for overlap: current video starts before other ends AND current ends after other starts
        if (startSec < rowEndSec && endSec > rowStartSec) {
          hasOverlap = true;
          conflictVideo = {
            startSec: rowStartSec,
            endSec: rowEndSec,
            $row: $row
          };
          return false; // break
        }
      });
      
      return { hasOverlap, conflictVideo };
    }

    // Validate time conflicts when user finishes editing
    $('#licenseTable').on('blur', '.start-time-input', function () {
      const $input = $(this);
      const normalized = normalizeDisplayTime($input.val());

      if (!normalized) {
        // Revert to previous desired time if current value invalid
        const fallback = getDesiredTime($input);
        $input.val(fallback);
        return;
      }

      if ($input.val() !== normalized) {
        $input.val(normalized);
      }

      // Get current row's duration for overlap check
      const $currentRow = $input.closest('tr');
      const currentDurationText = $currentRow.find('td').eq(5).text();
      const [currentMins, currentSecs] = currentDurationText.split(':').map(Number);
      const currentDuration = currentMins * 60 + currentSecs;

      // Validate that time doesn't cause overlaps with other items
      const newStartSec = timeToSeconds(normalized + ':00');
      
      // Check for overlaps
      const overlapCheck = checkVideoOverlap($input, newStartSec, currentDuration);
      
      if (overlapCheck.hasOverlap) {
        // Find nearest non-overlapping position
        const conflictEndSec = overlapCheck.conflictVideo.endSec;
        const adjustedStartSec = conflictEndSec; // Start right after the conflicting video
        
        const adjustedTimeWithSeconds = secondsToTimeString(adjustedStartSec);
        const adjustedDisplay = secondsToTimeStringShort(adjustedStartSec);
        
        // Update display time (HH:MM)
        $input.val(adjustedDisplay);
        setDesiredTime($input, adjustedDisplay);
        
        // Update internal time with seconds (HH:MM:SS)
        $input.data('internal-time', adjustedTimeWithSeconds);
        $input.siblings('.time-with-seconds').text(adjustedTimeWithSeconds);
        
        // Mark as manual time
        $input.data('manual-time', true);
        
        const adjustmentReason = gettext('Start time would cause overlap with another video. Adjusted to %(time)s.').replace('%(time)s', adjustedDisplay);
        $input.addClass('planning-input-error');
        showInlineNotice(adjustmentReason);
        notify(adjustmentReason, 'error');
        
        // Recalculate after alert to ensure everything is updated
        recalculateSchedule();
      } else {
        // Time is valid, set internal time
        const newStartTimeWithSeconds = secondsToTimeString(newStartSec);
        $input.data('internal-time', newStartTimeWithSeconds);
        $input.siblings('.time-with-seconds').text(newStartTimeWithSeconds);
        
        // Mark as manual time when user edits
        $input.data('manual-time', true);
        setDesiredTime($input, $input.val());
        $input.removeClass('planning-input-error');
        clearInlineNotice();
        recalculateSchedule();
        
        // Auto-sort after time change
        autoSortByTime();
      }
    });

    // Auto-sort rows by time (without button click)
    function autoSortByTime() {
      let rows = $('#licenseTable tbody tr:not(.gap-row)').get();
      rows.sort(function(a, b) {
        let $aInput = $(a).find('input[type="time"]');
        let $bInput = $(b).find('input[type="time"]');
        let aTimeStr = getInternalTime($aInput);
        let bTimeStr = getInternalTime($bInput);
        let aSec = timeToSeconds(aTimeStr);
        let bSec = timeToSeconds(bTimeStr);
        return aSec - bSec;
      });
      $.each(rows, function(idx, row) {
        $('#licenseTable tbody').append(row);
      });
      // Sync plannedItems with new order, but don't recalculate start times
      syncPlannedItemsFromTable();
      updateRemainingTime();
    }

    // Align all start times to 0 or 5 minutes
    $('#alignToFiveMinutesBtn').on('click', function () {
      // Collect all videos with their current positions
      const videos = [];
      const manualVideos = [];
      $('#licenseTable tbody tr:not(.gap-row)').each(function () {
        const $row = $(this);
        const $input = $row.find('.start-time-input');
        const isManualTime = $input.data('manual-time') === true;
        const startStr = getInternalTime($input); // Get time with seconds
        const durationText = $row.find('td').eq(5).text();
        const [mins, secs] = durationText.split(':').map(Number);
        const duration = mins * 60 + secs; // Already in seconds from MM:SS format
        
        if (startStr) {
          const startSec = timeToSeconds(startStr);
          const videoData = {
            $row: $row,
            startSec: startSec,
            duration: duration,
            originalIndex: $('#licenseTable tbody tr:not(.gap-row)').index($row)
          };
          
          if (isManualTime) {
            // Keep manual videos separate - they won't be aligned
            manualVideos.push(videoData);
          } else {
            videos.push(videoData);
          }
        }
      });
      
      // Sort by current start time
      videos.sort(function(a, b) {
        return a.startSec - b.startSec;
      });
      
      // Combine manual and auto videos, sort by start time
      const allVideos = [...manualVideos, ...videos].sort(function(a, b) {
        return a.startSec - b.startSec;
      });
      
      // Align each auto video to nearest 5-minute mark (minutes only), preserving seconds to follow previous video ends
      let currentPos = blockStart;
      videos.forEach(function(video, videoIndex) {
        // Check manual videos that might affect positioning
        let effectiveStartPos = currentPos;
        for (let i = 0; i < manualVideos.length; i++) {
          const manualVideo = manualVideos[i];
          const manualEndSec = manualVideo.startSec + manualVideo.duration;
          // If manual video is within block and affects positioning
          if (manualVideo.startSec >= blockStart && manualVideo.startSec < blockEnd) {
            if (manualEndSec > currentPos && manualEndSec <= blockEnd) {
              effectiveStartPos = Math.max(effectiveStartPos, manualEndSec);
            }
          }
        }
        
        // Find aligned position that keeps seconds continuity
        const roundedPos = alignToFiveMinutesKeepingSeconds(effectiveStartPos);
        
        // Check if rounded position would cause conflict with previous videos (both auto and manual)
        let finalPos = roundedPos;
        let hasConflict = false;
        let maxIterations = 100; // Safety limit
        let iterations = 0;
        
        do {
          hasConflict = false;
          iterations++;
          // Check against all already positioned auto videos
          for (let i = 0; i < videoIndex; i++) {
            const otherVideo = videos[i];
            const otherEndSec = otherVideo.finalPosSec + otherVideo.duration;
            const newEndSec = finalPos + video.duration;
            
            // Check for overlap (not touching)
            if (finalPos < otherEndSec && newEndSec > otherVideo.finalPosSec) {
              hasConflict = true;
              // Move to next 5-minute-aligned position after the conflicting video, keeping seconds continuity
              finalPos = alignToFiveMinutesKeepingSeconds(otherEndSec);
              break;
            }
          }
          
          // Also check against manual videos
          if (!hasConflict) {
            for (let i = 0; i < manualVideos.length; i++) {
              const manualVideo = manualVideos[i];
              const manualStartSec = manualVideo.startSec;
              const manualEndSec = manualStartSec + manualVideo.duration;
              const newEndSec = finalPos + video.duration;
              
              // Check for overlap with manual videos
              if (finalPos < manualEndSec && newEndSec > manualStartSec) {
                hasConflict = true;
                // Move to next 5-minute-aligned position after the conflicting manual video
                finalPos = alignToFiveMinutesKeepingSeconds(manualEndSec);
                break;
              }
            }
          }
        } while (hasConflict && iterations < maxIterations);
        
        // Store final position
        video.finalPosSec = finalPos;
        
        // Update the row
        const newStartTimeWithSeconds = secondsToTimeString(finalPos);
        const newStartTimeDisplay = timeToDisplay(newStartTimeWithSeconds);
        const $input = video.$row.find('.start-time-input');
        $input.val(newStartTimeDisplay); // Display only HH:MM
        $input.data('internal-time', newStartTimeWithSeconds); // Store with seconds
        $input.data('manual-time', false); // Auto-aligned items are not manual
        setDesiredTime($input, newStartTimeDisplay);
        $input.siblings('.time-with-seconds').text(newStartTimeWithSeconds); // Update time display
        const endSec = finalPos + video.duration;
        const endTimeString = secondsToTimeString(endSec);
        const endDayOffset = getDayOffset(endSec);
        let endTimeHTML = endTimeString;
        if (endDayOffset > 0) {
          endTimeHTML = endTimeString + '<br><small style="display: block; font-size: 11px; color: #6c757d; font-weight: normal;">(+' + endDayOffset + ' ' + gettext('day') + ')</small>';
        }
        video.$row.find('.end-time').html(endTimeHTML);
        
        // Move position forward for next video
        currentPos = finalPos + video.duration;
      });
      
      // Update plannedItems and re-sort rows by time
      syncPlannedItemsFromTable();
      
      // Re-sort table rows by new start times
      let rows = $('#licenseTable tbody tr:not(.gap-row)').get();
      rows.sort(function(a, b) {
        const $aInput = $(a).find('.start-time-input');
        const $bInput = $(b).find('.start-time-input');
        const aTime = getInternalTime($aInput);
        const bTime = getInternalTime($bInput);
        return aTime.localeCompare(bTime);
      });
      $.each(rows, function(idx, row) {
        $('#licenseTable tbody').append(row);
      });
      
      recalculateSchedule();
    });

    $('#licenseTable').on('click', '.remove-row', function () {
      const row = $(this).closest('tr');
      const index = $('#licenseTable tbody tr:not(.gap-row)').index(row);
      plannedItems.splice(index, 1);
      row.remove();
      syncPlannedItemsFromTable();
      recalculateSchedule();
    });

    function collectPlanData () {
      const isoDate = $('#dayPlanModal').data('isoDate');   // yyyy‑MM‑dd
      if (!isoDate) {
          notify(gettext('Date is missing.'), 'error');
          return null;
      }

      const items = [];

      $('#licenseTable tbody tr:not(.gap-row)').each(function (index) {
          const $row = $(this);
          const titleCell = $row.find('td').eq(3).text(); // index changed
          let title = titleCell;
          let subtitle = "";
          if (titleCell.includes(' – ')) {
            [title, subtitle] = titleCell.split(' – ', 2);
          }

          const durationText = $row.find('td').eq(5).text(); // Duration is now column 5
          const [mins, secs] = durationText.split(':').map(Number);
          const duration = mins * 60 + secs; // Already in seconds from MM:SS format

          // Extract license number from link or text
          const numberCell = $row.find('td').eq(2);
          let licenseNumber = numberCell.text().trim();
          // If it's a link, extract number from link text
          const linkText = numberCell.find('a').first().text();
          if (linkText) {
            licenseNumber = linkText.trim();
          }

          const $input = $row.find('.start-time-input');
          const item = {
              number:    parseInt(licenseNumber, 10),
              start:     getInternalTime($input), // Get time with seconds
              duration:  duration,
              title:     title,
              subtitle:  subtitle,
              sender_responsible: $row.find('td.sender-responsible').text(),
              license_id: $row.data('license-id') || null
          };

          items.push(item);
      });

      return {
          date: isoDate,
          items: items,
          comment: $('#noteText').val()
      };
    }

    $('#savePlanBtn').on('click', function () {
      const data = collectPlanData();
      if (!data) return;        // invalid date

      data.draft = true;

      $.ajax({
        url: '/api/day-plan/',
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify(data),
        beforeSend: addCsrfHeader,
        success: function (response) {
          notify(gettext('Draft saved successfully.'), 'success');
          location.reload(); // refresh calendar
        },
        error: function (xhr) {
          renderValidationErrors(xhr, gettext("Error saving the draft."));
        }
      });
    });

    $('#planPlanBtn').on('click', function () {
      const data = collectPlanData(); // no draft
      if (!data) return;        // invalid date

      data.planned = true;

      $.ajax({
        url: '/api/day-plan/',
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify(data),
        beforeSend: addCsrfHeader,
        success: function (response) {
          var message = gettext('Plan saved successfully!');
          notify(message, 'success');
          const modal = bootstrap.Modal.getInstance(document.getElementById('dayPlanModal'));
          modal.hide();
          location.reload(); // refresh calendar
        },
        error: function (xhr) {
          renderValidationErrors(xhr, gettext("Error saving the plan. Please try again."));
        }
      });
    });

    $('#exportPlanBtn').on('click', function () {
      const isoDate = $('#dayPlanModal').data('isoDate');
      if (!isoDate) {
        notify(gettext('Date is missing.'), 'error');
        return;
      }
      window.open('/api/day-plan/' + isoDate + '/export/', '_blank');
    });

    $('#copyFromDateBtn').on('click', function () {
      const targetDate = $('#dayPlanModal').data('isoDate');
      if (!targetDate) {
        notify(gettext('Date is missing.'), 'error');
        return;
      }
      openActionModal({
        title: gettext('Copy plan'),
        message: gettext('Select source date'),
        withInput: true,
        inputType: 'date',
        inputLabel: gettext('Source date'),
        confirmText: gettext('Copy from date')
      }).then(function (sourceDate) {
        if (!sourceDate) return;

        $.ajax({
          url: '/api/planning/copy/',
          method: 'POST',
          contentType: 'application/json',
          data: JSON.stringify({ source_date: sourceDate, target_date: targetDate, overwrite: true }),
          beforeSend: addCsrfHeader,
          success: function () {
            notify(gettext('Plan copied successfully.'), 'success');
            location.reload();
          },
          error: function (xhr) {
            renderValidationErrors(xhr, gettext('Error copying plan.'));
          }
        });
      });
    });

    $('#applyTemplateBtn').on('click', function () {
      const targetDate = $('#dayPlanModal').data('isoDate');
      const templateId = $('#templateSelect').val();
      if (!targetDate) {
        notify(gettext('Date is missing.'), 'error');
        return;
      }
      if (!templateId) {
        notify(gettext('Please select a template.'), 'error');
        return;
      }
      $.ajax({
        url: '/api/planning/templates/apply/',
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({ date: targetDate, template_id: templateId, overwrite: true }),
        beforeSend: addCsrfHeader,
        success: function () {
          notify(gettext('Template applied successfully.'), 'success');
          location.reload();
        },
        error: function (xhr) {
          renderValidationErrors(xhr, gettext('Error applying template.'));
        }
      });
    });

    function getCookie(name) {
      let cookieValue = null;
      if (document.cookie && document.cookie !== '') {
          const cookies = document.cookie.split(';');
          for (let i = 0; i < cookies.length; i++) {
              const cookie = cookies[i].trim();
              if (cookie.substring(0, name.length + 1) === (name + '=')) {
                  cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                  break;
              }
          }
      }
      return cookieValue;
    }
    function getCsrfToken() {
      if (typeof PLANNING_CSRF_TOKEN === 'string' && PLANNING_CSRF_TOKEN && PLANNING_CSRF_TOKEN !== 'NOTPROVIDED') {
        return PLANNING_CSRF_TOKEN;
      }
      return getCookie('csrftoken');
    }

    function addCsrfHeader(xhr) {
      const csrfToken = getCsrfToken();
      if (csrfToken) {
        xhr.setRequestHeader('X-CSRFToken', csrfToken);
      }
    }

    $('#deletePlanBtn').on('click', function () {
      const isoDate = $('#dayPlanModal').data('isoDate');
      if (!isoDate) {
          notify(gettext('Date is missing.'), 'error');
          return;
      }
      openActionModal({
        title: gettext('Delete plan'),
        message: gettext('Delete plan for this day?'),
        withInput: false,
        confirmText: gettext('Delete')
      }).then(function (confirmed) {
        if (!confirmed) return;

        $.ajax({
          url: '/api/day-plan/' + isoDate + '/',
          method: 'DELETE',
          beforeSend: addCsrfHeader,
          success: function () {
            notify(gettext('Plan deleted!'), 'success');
            const modal = bootstrap.Modal.getInstance(document.getElementById('dayPlanModal'));
            modal.hide();
            location.reload(); // refresh calendar
          },
          error: function () {
            notify(gettext('Error deleting the plan.'), 'error');
          }
        });
      });
    });

    // Drag-and-drop rows (only non-gap rows)
    $('#licenseTable tbody').sortable({
      items: 'tr:not(.gap-row)',
      handle: '.drag-handle',
      update: function () {
        recalculateAllStartTimes();
        syncPlannedItemsFromTable();
        updateRemainingTime();
      }
    });

    // Time sort button
    $('#sortByTimeBtn').on('click', function () {
      autoSortByTime();
    });

    // Synchronize plannedItems with the table
    function syncPlannedItemsFromTable() {
      plannedItems = [];
      $('#licenseTable tbody tr:not(.gap-row)').each(function () {
        const $row = $(this);
        const $input = $row.find('.start-time-input');
        const start = getInternalTime($input); // Get time with seconds
        const numberCell = $row.find('td').eq(2);
        let licenseNumber = numberCell.text().trim();
        const linkText = numberCell.find('a').first().text();
        if (linkText) {
          licenseNumber = linkText.trim();
        }
        const titleCell = $row.find('td').eq(3).text();
        let [title, subtitle] = titleCell.split(' – ', 2);
        const senderResponsible = $row.find('td.sender-responsible').text();
        const durationText = $row.find('td').eq(5).text(); // Duration is now column 5
        const [mins, secs] = durationText.split(':').map(Number);
        const duration = mins * 60 + secs; // Already in seconds from MM:SS format
        plannedItems.push({ 
          start, 
          number: parseInt(licenseNumber, 10), 
          title, 
          subtitle, 
          sender_responsible: senderResponsible,
          license_id: $row.data('license-id') || null,
          duration 
        });
      });
    }

    // Recalculate start times for all videos in sequence
    function recalculateAllStartTimes() {
      var currentPos = blockStart;
      
      $('#licenseTable tbody tr:not(.gap-row)').each(function () {
        const $row = $(this);
        const $input = $row.find('.start-time-input');
        const isManualTime = $input.data('manual-time') === true;
        
        // Skip manual time items
        if (isManualTime) {
          const startStr = getInternalTime($input);
          const startSec = timeToSeconds(startStr);
          const durationText = $row.find('td').eq(5).text();
          const [mins, secs] = durationText.split(':').map(Number);
          const duration = mins * 60 + secs;
          // Update currentPos to be after this manual item if it's within block
          if (startSec >= blockStart && startSec < blockEnd) {
            currentPos = Math.max(currentPos, startSec + duration);
          }
          return; // Skip this row
        }
        
        const durationText = $row.find('td').eq(5).text(); // Duration is now column 5
        const [mins, secs] = durationText.split(':').map(Number);
        const duration = mins * 60 + secs; // Already in seconds from MM:SS format
        
        // Calculate rounded position
        const roundedPos = roundToFiveMinutes(currentPos);
        const newStartTimeWithSeconds = secondsToTimeString(roundedPos);
        const newStartTimeDisplay = timeToDisplay(newStartTimeWithSeconds);
        
        // Update start time input
        $input.val(newStartTimeDisplay); // Display only HH:MM
        $input.data('internal-time', newStartTimeWithSeconds); // Store with seconds
        setDesiredTime($input, newStartTimeDisplay);
        $input.data('manual-time', false); // Auto-positioned items are not manual
        $input.siblings('.time-with-seconds').text(newStartTimeWithSeconds); // Update time display
        
        // Update end time display with day offset if needed
        const endSec = roundedPos + duration;
        const endTimeString = secondsToTimeString(endSec);
        const endDayOffset = getDayOffset(endSec);
        let endTimeHTML = endTimeString;
        if (endDayOffset > 0) {
          endTimeHTML = endTimeString + '<br><small style="display: block; font-size: 11px; color: #6c757d; font-weight: normal;">(+' + endDayOffset + ' ' + gettext('day') + ')</small>';
        }
        $row.find('.end-time').html(endTimeHTML);
        
        // Move position forward
        currentPos = endSec;
      });
      
      // Sync plannedItems before recalculateSchedule to ensure correct duration is used
      syncPlannedItemsFromTable();
      // recalculateSchedule will update visual indicators but should preserve the rounded times
      recalculateSchedule();
    }

    function toIsoDateLocal(dateObj) {
      var y = dateObj.getFullYear();
      var m = (dateObj.getMonth() + 1).toString().padStart(2, '0');
      var d = dateObj.getDate().toString().padStart(2, '0');
      return y + '-' + m + '-' + d;
    }

    function getCurrentWeekMondayIso() {
      var now = new Date();
      var day = now.getDay();
      var mondayOffset = day === 0 ? 6 : day - 1;
      now.setHours(0, 0, 0, 0);
      now.setDate(now.getDate() - mondayOffset);
      return toIsoDateLocal(now);
    }

    // Function to load and display weekly statistics
    var loadWeeklyStatistics = function() {
      // Stats cards always represent current week and next weeks,
      // independent from the visible calendar range in the table.
      var startDate = getCurrentWeekMondayIso();
      $.get('/api/planning/week-stats/?start=' + startDate + '&weeks=4')
        .done(function (response) {
          (response.weeks || []).forEach(function (weekData, idx) {
            updateWeekStatistics(idx, {
              planned: Number(weekData.planned_days || 0),
              totalTime: Number(weekData.total_seconds || 0),
              licensesCount: Number(weekData.licenses_count || 0),
              maxSeconds: Number(weekData.max_seconds || 0),
            });
          });
        });
    };

    // Update statistics display for specific week
    var updateWeekStatistics = function(weekIndex, data) {
      var weekIds = ['currentWeek', 'nextWeek', 'afterNextWeek', 'threeWeeksAhead'];
      var weekId = weekIds[weekIndex];

      if (weekId) {
        var maxWeeklyTime = data.maxSeconds || (maxBlockSeconds * 7);
        var fillRate = maxWeeklyTime > 0 ? Math.round((data.totalTime / maxWeeklyTime) * 100) : 0;
        
        var totalMins = Math.floor(data.totalTime / 60);
        var maxMins = Math.floor(maxWeeklyTime / 60);
        
        var timeText = data.totalTime > maxWeeklyTime ?
          (totalMins + '/' + maxMins + ' min (' + (totalMins - maxMins) + ' over)') :
          (totalMins + '/' + maxMins + ' min');

        $('#' + weekId + 'Planned').text(data.planned);
        $('#' + weekId + 'Time').text(timeText);
        $('#' + weekId + 'Fill').text(fillRate + '%');
        $('#' + weekId + 'TimeOff').text(data.licensesCount || 0);

        // Color coding for fill rate
        var fillElement = $('#' + weekId + 'Fill');
        if (fillRate > 100) {
          fillElement.removeClass('text-success text-warning').addClass('text-danger');
        } else if (fillRate > 80) {
          fillElement.removeClass('text-success text-danger').addClass('text-warning');
        } else {
          fillElement.removeClass('text-warning text-danger').addClass('text-success');
        }
      } else {
        console.error('Invalid weekIndex:', weekIndex);
      }
    };

    function normalizeSearchText(value) {
      return (value || '')
        .toString()
        .normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '')
        .toLowerCase()
        .trim();
    }

    function getDateCellText($cell) {
      var text = normalizeSearchText($cell.text());
      var searchData = normalizeSearchText($cell.data('search') || '');
      return (text + ' ' + searchData).trim();
    }

    function applyCalendarFilters() {
      var query = normalizeSearchText($('#calendarSearchInput').val() || '');
      var status = $('#calendarStatusFilter').val();

      $('.date-cell').each(function () {
        var $btn = $(this);
        var $td = $btn.closest('td');
        var cellText = getDateCellText($btn);
        var hasComment = String($btn.data('has-comment')).toLowerCase() === 'true';
        var tdStatus = $td.data('status');
        var isPlanned = tdStatus === 'planned';
        var isDraft = tdStatus === 'draft';
        var isEmpty = tdStatus === 'empty';
        var isOutside = tdStatus === 'outside';

        var statusOk = true;
        if (status === 'planned') statusOk = isPlanned;
        if (status === 'draft') statusOk = isDraft;
        if (status === 'comment') statusOk = hasComment;
        if (status === 'empty') statusOk = isEmpty;
        if (status === 'outside') statusOk = isOutside;

        var queryOk = !query || cellText.indexOf(query) >= 0;
        var visible = statusOk && queryOk;

        $td.toggleClass('planning-cell-filtered-out', !visible);
        $btn.attr('aria-hidden', visible ? 'false' : 'true');
        $btn.attr('tabindex', visible ? '0' : '-1');
      });
    }

    var debouncedApplyCalendarFilters = debounce(applyCalendarFilters, 160);
    $('#calendarSearchInput').on('input', debouncedApplyCalendarFilters);
    $('#calendarStatusFilter').on('change', applyCalendarFilters);

    function shiftCalendarWeeks(deltaWeeks) {
      if (!calendarStartDate || isNaN(calendarStartDate.getTime())) {
        calendarStartDate = new Date();
      }
      calendarStartDate.setDate(calendarStartDate.getDate() + (deltaWeeks * 7));
      var iso = formatLocalDate(calendarStartDate);
      window.location.href = '/admin/planung/tagesplan/calendar-weeks/?start=' + iso + '&weeks=' + (CALENDAR_WEEKS || 18);
    }

    $('#navPrevWeeksBtn').on('click', function () { shiftCalendarWeeks(-4); });
    $('#navNextWeeksBtn').on('click', function () { shiftCalendarWeeks(4); });
    $('#navTodayBtn').on('click', function () {
      var now = new Date();
      var day = now.getDay();
      var mondayOffset = day === 0 ? 6 : day - 1;
      now.setDate(now.getDate() - mondayOffset);
      var iso = formatLocalDate(now);
      window.location.href = '/admin/planung/tagesplan/calendar-weeks/?start=' + iso + '&weeks=' + (CALENDAR_WEEKS || 18);
    });

    // Load weekly statistics after all functions are defined
    loadTemplates();
    loadWeeklyStatistics();

    // Playout integration: show buttons only when configured
    $.ajax({
      url: '/api/planning/playout/config/',
      method: 'GET',
      dataType: 'json',
      success: function (cfg) {
        if (cfg.import_configured) {
          $('#sendMetadataBtn').show();
        }
        if (cfg.schedule_configured) {
          $('#sendScheduleBtn').show();
        }
        if (cfg.anchor_configured) {
          $('#renderAnchorBtn').show();
        }
      }
    });

    function checkDayPlanStatus() {
      var iso = $('#dayPlanModal').data('iso-date');
      var $metaBtn = $('#sendMetadataBtn');
      var $schedBtn = $('#sendScheduleBtn');
      var $anchorBtn = $('#renderAnchorBtn');
      if (!iso) {
        $metaBtn.prop('disabled', true).attr('title', gettext('Select a day first'));
        $schedBtn.prop('disabled', true).attr('title', gettext('Select a day first'));
        $anchorBtn.prop('disabled', true).attr('title', gettext('Select a day first'));
        return;
      }
      $.ajax({
        url: '/api/day-plan/' + iso + '/',
        method: 'GET',
        dataType: 'json',
        success: function (data) {
          var isPlanned = data && data.planned;
          if (isPlanned) {
            $metaBtn.prop('disabled', false).attr('title', gettext('Send media metadata to playout'));
            $schedBtn.prop('disabled', false).attr('title', gettext('Send schedule to playout'));
            $anchorBtn.prop('disabled', false).attr('title', gettext('Render programme preview'));
          } else {
            $metaBtn.prop('disabled', true).attr('title', gettext('Plan the day first'));
            $schedBtn.prop('disabled', true).attr('title', gettext('Plan the day first'));
            $anchorBtn.prop('disabled', true).attr('title', gettext('Plan the day first'));
          }
        },
        error: function () {
          $metaBtn.prop('disabled', true).attr('title', gettext('No plan for this day'));
          $schedBtn.prop('disabled', true).attr('title', gettext('No plan for this day'));
          $anchorBtn.prop('disabled', true).attr('title', gettext('No plan for this day'));
        }
      });
    }

    $('#dayPlanModal').on('shown.bs.modal', checkDayPlanStatus);

    $('#sendMetadataBtn').on('click', function () {
      var iso = $('#dayPlanModal').data('iso-date');
      if (!iso) {
        notify(gettext('Date is missing.'), 'error');
        return;
      }
      var $btn = $(this);
      $btn.prop('disabled', true);
      $.ajax({
        url: '/api/planning/playout/metadata/',
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({ date: iso }),
        beforeSend: addCsrfHeader,
        success: function (response) {
          if (response.error) {
            notify(gettext('Playout metadata failed: ') + response.error, 'error');
          } else if (response.matched !== undefined) {
            notify(gettext('Playout metadata sent. Matched: ') + response.matched, 'success');
          } else {
            notify(gettext('Playout metadata sent.'), 'success');
          }
        },
        error: function (xhr) {
          notify(gettext('Playout metadata request failed.'), 'error');
        },
        complete: function () {
          $btn.prop('disabled', false);
        }
      });
    });

    $('#sendScheduleBtn').on('click', function () {
      var iso = $('#dayPlanModal').data('iso-date');
      if (!iso) {
        notify(gettext('Date is missing.'), 'error');
        return;
      }
      var $btn = $(this);
      $btn.prop('disabled', true);
      $.ajax({
        url: '/api/planning/playout/schedule/',
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({ date: iso }),
        beforeSend: addCsrfHeader,
        success: function (response) {
          if (response.error) {
            notify(gettext('Playout schedule failed: ') + response.error, 'error');
          } else if (Number(response.placeholders_created || 0) > 0) {
            notify(gettext('Playout schedule sent. Placeholders: ') + response.placeholders_created, 'success');
          } else if (response.created !== undefined) {
            notify(gettext('Playout schedule sent. Created: ') + response.created, 'success');
          } else {
            notify(gettext('Playout schedule sent.'), 'success');
          }
        },
        error: function (xhr) {
          notify(gettext('Playout schedule request failed.'), 'error');
        },
        complete: function () {
          $btn.prop('disabled', false);
        }
      });
    });

    var POLL_INTERVAL_MS = 15000;       // 15 seconds between status checks
    var MAX_POLL_ATTEMPTS = 120;        // 30 minutes total (120 × 15s)
    var RENDER_RETRY_DELAY_MS = 30000;  // 30 seconds retry when videos still copying

    function renderAnchorPreview(force) {
      var iso = $('#dayPlanModal').data('iso-date');
      if (!iso) {
        notify(gettext('Date is missing.'), 'error');
        return Promise.resolve();
      }
      var $btn = $('#renderAnchorBtn');
      $btn.prop('disabled', true);
      return $.ajax({
        url: '/api/planning/anchor/render/',
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({ date: iso, force: Boolean(force) }),
        beforeSend: addCsrfHeader,
        success: function (response) {
          if (response.status === 'queued' && response.task_id) {
            notify(gettext('Programme preview render started. You can close this window — it continues in the background.'), 'info');
            pollRenderStatus(response.task_id, $btn, 0);
          } else {
            notify(gettext('Programme preview render task queued.'), 'success');
            $btn.prop('disabled', false);
          }
        },
        error: function (xhr) {
          var response = xhr.responseJSON || {};
          if (xhr.status === 409 && response.error === 'videos_still_copying') {
            var missing = (response.missing && response.missing.length)
              ? gettext('Missing: ') + response.missing.join(', ')
              : '';
            notify(gettext('Videos are still being copied to the playout storage. Retrying in 30 seconds...') + (missing ? ' ' + missing : ''), 'info');
            setTimeout(function () { renderAnchorPreview(force); }, RENDER_RETRY_DELAY_MS);
            return;
          }
          if (xhr.status === 409 && response.error === 'copy_failed') {
            showCopyFailedDialog(response, $btn);
            return;
          }
          if (xhr.status === 409 && response.requires_confirmation) {
            openActionModal({
              title: gettext('Render programme preview again?'),
              message: gettext('A programme preview video already exists for this day. Recreate it and overwrite the existing output file?'),
              confirmText: gettext('Recreate')
            }).then(function (confirmed) {
              if (confirmed) {
                renderAnchorPreview(true);
              } else {
                $btn.prop('disabled', false);
              }
            });
            return;
          }
          var message = response.error || gettext('Programme preview render request failed.');
          notify(message, 'error');
          $btn.prop('disabled', false);
        }
      });
    }

    function pollRenderStatus(taskId, $btn, attempts) {
      if (attempts >= MAX_POLL_ATTEMPTS) {
        notify(gettext('Programme preview render is taking too long. Check the Celery task results in the admin panel.'), 'error');
        $btn.prop('disabled', false);
        return;
      }
      setTimeout(function () {
        $.ajax({
          url: '/api/planning/anchor/render/status/' + taskId + '/',
          method: 'GET',
          beforeSend: addCsrfHeader,
          success: function (response) {
            if (response.state === 'SUCCESS') {
              var r = response.result || {};
              if (r.status === 'error' || r.error) {
                notify(gettext('Programme preview render failed: ') + (r.error || r.status), 'error');
              } else if (r.status === 'done') {
                notify(gettext('Programme preview render completed: ') + (r.file || r.output_name), 'success');
              } else {
                notify(gettext('Programme preview render completed: ') + (r.file || r.output_name || 'done'), 'success');
              }
              $btn.prop('disabled', false);
            } else if (response.state === 'FAILURE') {
              var r = response.result || {};
              notify(gettext('Programme preview render failed: ') + (r.error || 'unknown'), 'error');
              $btn.prop('disabled', false);
            } else {
              pollRenderStatus(taskId, $btn, attempts + 1);
            }
          },
          error: function () {
            pollRenderStatus(taskId, $btn, attempts + 1);
          }
        });
      }, POLL_INTERVAL_MS);
    }

    function buildCopyFailedMessage(response) {
      var lines = [];
      if (response.copy_task_id) {
        var adminUrl = '/admin/django_celery_results/taskresult/?task_id=' + encodeURIComponent(response.copy_task_id);
        lines.push(gettext('Video copy failed. Check the Celery task result for details.'));
        lines.push(gettext('Task ID: ') + response.copy_task_id);
        lines.push(adminUrl);
      } else {
        lines.push(gettext('Video copy failed. Please check the plan and try again.'));
      }
      if (response.ready && response.ready.length) {
        lines.push(gettext('Ready: ') + response.ready.join(', '));
      }
      if (response.missing && response.missing.length) {
        lines.push(gettext('Missing/Failed: ') + response.missing.join(', '));
      }
      return lines.join('\n');
    }

    function showCopyFailedDialog(response, $btn) {
      if (!window.bootstrap || !bootstrap.Modal) {
        notify(buildCopyFailedMessage(response), 'error');
        promptForceRenderAnyway($btn);
        return;
      }
      var modalEl = document.getElementById('planningActionModal');
      if (!modalEl) {
        notify(buildCopyFailedMessage(response), 'error');
        promptForceRenderAnyway($btn);
        return;
      }
      var $message = $('#planningActionMessage');
      var $input = $('#planningActionInput');
      var $inputLabel = $('#planningActionInputLabel');
      var $confirmBtn = $('#planningActionConfirmBtn');

      $('#planningActionLabel').text(gettext('Video copy failed'));
      $message.text(buildCopyFailedMessage(response));
      $input.prop('hidden', true).val('');
      $inputLabel.text('');

      var $modal = bootstrap.Modal.getOrCreateInstance(modalEl);
      var originalConfirm = $confirmBtn.text();
      $confirmBtn.text(gettext('Render anyway'));
      var handler = function () {
        renderAnchorPreview(true);
        $modal.hide();
        $confirmBtn.off('click', handler);
        $confirmBtn.text(originalConfirm);
      };
      $confirmBtn.on('click', handler);
      modalEl.addEventListener('hidden.bs.modal', function () {
        $btn.prop('disabled', false);
        $confirmBtn.off('click', handler);
        $confirmBtn.text(originalConfirm);
      }, { once: true });
      $modal.show();
    }

    function promptForceRenderAnyway($btn) {
      if (window.confirm(gettext('Render anyway with the current files?'))) {
        renderAnchorPreview(true);
      } else {
        $btn.prop('disabled', false);
      }
    }

    $('#renderAnchorBtn').on('click', function () {
      renderAnchorPreview(false);
    });

  });
})(jQuery);

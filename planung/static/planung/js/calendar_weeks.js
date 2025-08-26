(function ($) {
  $(function () {
    var $modal = $('#dayPlanModal');
    var plannedItems = [];
    const blockStart = 18 * 60;
    const blockEnd = 19 * 60 + 45;
    const maxBlockMinutes = blockEnd - blockStart;

    // Load weekly statistics on page load
    // (function will be called after it's defined below)

    $('.date-cell').on('click', function () {
          const iso = $(this).data('date');
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
                    const row = '<tr>' +
                      '<td><input type="time" class="form-control input-sm start-time-input" value="' + item.start + '"></td>' +
                      '<td>' + item.number + '</td>' +
                      '<td>' + (item.title || '') + (item.subtitle ? ' – ' + item.subtitle : '') + '</td>' +
                      '<td>' + item.duration + '</td>' +
                      '<td><span class="drag-handle" style="cursor:move;font-size:18px;margin-right:6px;">&#9776;</span><button class="btn btn-xs btn-danger remove-row">&times;</button></td>' +
                      '</tr>';
                    $('#licenseTable tbody').append(row);
                    plannedItems.push({
                      number: item.number,
                      duration: item.duration,
                      title: item.title,
                      subtitle: item.subtitle,
                      start: item.start
                    });
                });

                $('#noteText').val(data.comment || '');
                updateRemainingTime();
            })
            .fail(function () {
                // 404 - means no plan exists yet, leave modal empty
            });

          const modal = new bootstrap.Modal(document.getElementById('dayPlanModal'));
          modal.show();
      });

    function updateRemainingTime() {
      var totalUsedTime = 0;
      var videoItems = [];

      // Собираем все видео с временем начала и длительностью
      $('#licenseTable tbody tr').each(function () {
        const $row = $(this);
        const startStr = $row.find('input[type="time"]').val();
        const duration = parseInt($row.find('td').eq(3).text(), 10);
        if (startStr && duration) {
          const [h, m] = startStr.split(":").map(Number);
          const startMin = h * 60 + m;
          const endMin = startMin + duration;
          videoItems.push({
            start: startMin,
            end: endMin,
            duration: duration
          });
        }
      });

      if (videoItems.length > 0) {
        // Сортируем по времени начала
        videoItems.sort(function(a, b) {
          return a.start - b.start;
        });

        // Считаем общее занятое время
        var currentEnd = blockStart; // начинаем с 18:00

        for (var i = 0; i < videoItems.length; i++) {
          var item = videoItems[i];

          // Если есть промежуток больше 5 минут, добавляем его к занятому времени
          if (item.start - currentEnd > 5) {
            totalUsedTime += (item.start - currentEnd);
          }

          // Добавляем время видео
          totalUsedTime += item.duration;
          currentEnd = item.end;
        }
      }

      const remaining = maxBlockMinutes - totalUsedTime;
      const $remaining = $('#remainingTime');

      if (remaining < 0) {
        $remaining.removeClass('text-success').addClass('text-danger')
          .text(TEXTS.overPlanned.replace('%(minutes)s', -remaining));
      } else {
        $remaining.removeClass('text-danger').addClass('text-success')
          .text(TEXTS.stillFree.replace('%(minutes)s', remaining));
      }
    }

    $('#addLicenseBtn').on('click', function () {
      const number = $('#licenseNumberInput').val().trim();
      if (!number) return;

      $.get('/api/license/' + number + '/', function (data) {
        // calculate start time as maximum end time
        let lastEnd = blockStart;
        plannedItems.forEach(function(item) {
          // convert start to minutes
          let startMin = 0;
          if (item.start && /^\d{2}:\d{2}$/.test(item.start)) {
            const [h, m] = item.start.split(":").map(Number);
            startMin = h * 60 + m;
          }
          lastEnd = Math.max(lastEnd, startMin + (item.duration || 0));
        });
        const startTime = Math.floor(lastEnd / 60).toString().padStart(2, '0') + ':' +
                          (lastEnd % 60).toString().padStart(2, '0');

        const row = '<tr>' +
          '<td><input type="time" class="form-control input-sm start-time-input" value="' + startTime + '"></td>' +
          '<td>' + data.number + '</td>' +
          '<td>' + data.title + (data.subtitle ? ' – ' + data.subtitle : '') + '</td>' +
          '<td>' + data.duration_min + '</td>' +
          '<td><span class="drag-handle" style="cursor:move;font-size:18px;margin-right:6px;">&#9776;</span><button class="btn btn-xs btn-danger remove-row">&times;</button></td>' +
          '</tr>';

        $('#licenseTable tbody').append(row);
        plannedItems.push({
          number: data.number,
          duration: data.duration_min,
          title: data.title,
          subtitle: data.subtitle,
          start: startTime
        });
        updateRemainingTime();
        $('#licenseNumberInput').val('');
      }).fail(function () {
        alert(TEXTS.licenseNotFound);
      });
    });

    // Synchronize start time when input changes
    $('#licenseTable').on('change input', '.start-time-input', function () {
      const $row = $(this).closest('tr');
      const index = $row.index();
      const newStart = $(this).val();
      if (plannedItems[index]) {
        plannedItems[index].start = newStart;
      }
      updateRemainingTime();
    });

    $('#licenseTable').on('click', '.remove-row', function () {
      const row = $(this).closest('tr');
      const index = row.index();
      plannedItems.splice(index, 1);
      row.remove();
      updateRemainingTime();
    });

    function collectPlanData () {
      const isoDate = $('#dayPlanModal').data('isoDate');   // yyyy‑MM‑dd
      if (!isoDate) {
          alert("⚠️ Date is missing.");
          return null;
      }

      const items = [];

      $('#licenseTable tbody tr').each(function (index) {
          const $row = $(this);
          const titleCell = $row.find('td').eq(2).text();
          let title = titleCell;
          let subtitle = "";
          if (titleCell.includes(' – ')) {
            [title, subtitle] = titleCell.split(' – ', 2);
          }

          const item = {
              number:    parseInt($row.find('td').eq(1).text(), 10),
              start:     $row.find('input[type="time"]').val(),
              duration:  parseInt($row.find('td').eq(3).text(), 10),
              title:     title,
              subtitle:  subtitle
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
        success: function (response) {
          alert("Draft saved successfully.");
          location.reload(); // refresh calendar
        },
        error: function (xhr, status, error) {
          alert("Error saving the draft.");
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
        success: function () {
          alert("Plan saved successfully!");
          const modal = bootstrap.Modal.getInstance(document.getElementById('dayPlanModal'));
          modal.hide();
          location.reload(); // refresh calendar
        },
        error: function () {
          alert("Error saving the plan. Please try again.");
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
    const csrftoken = getCookie('csrftoken');

    $('#dayPlanModal .btn-danger').on('click', function () {
      const isoDate = $('#dayPlanModal').data('isoDate');
      if (!isoDate) {
          alert("⚠️ Date is missing.");
          return;
      }
      if (!confirm("Delete plan for this day?")) return;

      $.ajax({
        url: '/api/day-plan/' + isoDate + '/',
        method: 'DELETE',
        beforeSend: function(xhr) {
          xhr.setRequestHeader('X-CSRFToken', csrftoken);
        },
        success: function () {
          alert("Plan deleted!");
          const modal = bootstrap.Modal.getInstance(document.getElementById('dayPlanModal'));
          modal.hide();
          location.reload(); // refresh calendar
        },
        error: function () {
          alert("Error deleting the plan.");
        }
      });
    });

    // Drag-and-drop rows
    $('#licenseTable tbody').sortable({
      handle: '.drag-handle',
      update: function () {
        syncPlannedItemsFromTable();
        updateRemainingTime();
      }
    });

    // Time sort button
    $('#sortByTimeBtn').on('click', function () {
      let rows = $('#licenseTable tbody tr').get();
      rows.sort(function(a, b) {
        let aTime = $(a).find('input[type="time"]').val();
        let bTime = $(b).find('input[type="time"]').val();
        return aTime.localeCompare(bTime);
      });
      $.each(rows, function(idx, row) {
        $('#licenseTable tbody').append(row);
      });
      syncPlannedItemsFromTable();
      updateRemainingTime();
    });

    // Synchronize plannedItems with the table
    function syncPlannedItemsFromTable() {
      plannedItems = [];
      $('#licenseTable tbody tr').each(function () {
        const $row = $(this);
        const start = $row.find('input[type="time"]').val();
        const number = $row.find('td').eq(1).text();
        const titleCell = $row.find('td').eq(2).text();
        let [title, subtitle] = titleCell.split(' – ', 2);
        const duration = parseInt($row.find('td').eq(3).text(), 10);
        plannedItems.push({ start, number, title, subtitle, duration });
      });
    }

    // Function to load and display weekly statistics
    var loadWeeklyStatistics = function() {
      var currentWeek = parseInt(CURRENT_WEEK, 10);
      var weeks = [currentWeek, currentWeek + 1, currentWeek + 2, currentWeek + 3];

      weeks.forEach(function(weekNum, weekIndex) {
        var weekData = {
          planned: 0,
          totalTime: 0,
          freistellungen: new Set() // Уникальные номера лицензий
        };

        // Get all dates for this week
        var weekStart = getWeekStartDate(weekNum);

        // Create unique counter for this week
        var weekCounter = {
          daysProcessed: 0,
          totalDays: 7
        };

        // Load data for each day in the week
        for (var i = 0; i < 7; i++) {
          var date = new Date(weekStart);
          date.setDate(date.getDate() + i + 1);  // +1 день для сдвига
          var isoDate = date.toISOString().split('T')[0];

          // Use IIFE to create proper closure for weekIndex and counters
          (function(currentWeekIndex, currentWeekData, currentWeekCounter) {
            var apiUrl = '/api/day-plan/' + isoDate + '/';

            $.get(apiUrl)
              .done(function (data) {

                if (data.items && data.items.length > 0) {
                  currentWeekData.planned++;
                  data.items.forEach(function(item) {
                    currentWeekData.totalTime += item.duration || 0;
                    // Добавляем номер лицензии в Set для уникальности
                    if (item.number) {
                      currentWeekData.freistellungen.add(item.number);
                    }
                  });
                }

                currentWeekCounter.daysProcessed++;

                // Update statistics only when all days are processed
                if (currentWeekCounter.daysProcessed === currentWeekCounter.totalDays) {
                  updateWeekStatistics(currentWeekIndex, currentWeekData);
                }
              })
              .fail(function (xhr, status, error) {
                currentWeekCounter.daysProcessed++;

                // Update statistics even if some days failed
                if (currentWeekCounter.daysProcessed === currentWeekCounter.totalDays) {
                  updateWeekStatistics(currentWeekIndex, currentWeekData);
                }
              });
          })(weekIndex, weekData, weekCounter);
        }
      });
    };

    // Helper functions for date calculations
    var getWeekStartDate = function(weekNum) {
      // Calculate start date for given week number
      var currentYear = new Date().getFullYear();
      var jan1 = new Date(currentYear, 0, 1);
      var days = (weekNum - 1) * 7;
      var weekStart = new Date(jan1.getTime() + days * 24 * 60 * 60 * 1000);

      // Adjust to Monday
      var dayOfWeek = weekStart.getDay();
      var mondayOffset = dayOfWeek === 0 ? 6 : dayOfWeek - 1;
      weekStart.setDate(weekStart.getDate() - mondayOffset);

      return weekStart;
    };

    var getWeekEndDate = function(weekNum) {
      var weekStart = getWeekStartDate(weekNum);
      var weekEnd = new Date(weekStart);
      weekEnd.setDate(weekEnd.getDate() + 6);
      return weekEnd;
    };

    // Update statistics display for specific week
    var updateWeekStatistics = function(weekIndex, data) {
      var weekIds = ['currentWeek', 'nextWeek', 'afterNextWeek', 'threeWeeksAhead'];
      var weekId = weekIds[weekIndex];

      if (weekId) {
        var maxWeeklyTime = 105 * 7; // 735 минут за неделю (7 дней × 105 мин)
        var fillRate = Math.round((data.totalTime / maxWeeklyTime) * 100);
        var timeText = data.totalTime > maxWeeklyTime ?
          (data.totalTime + '/' + maxWeeklyTime + ' min (' + (data.totalTime - maxWeeklyTime) + ' over)') :
          (data.totalTime + '/' + maxWeeklyTime + ' min');

        $('#' + weekId + 'Planned').text(data.planned);
        $('#' + weekId + 'Time').text(timeText);
        $('#' + weekId + 'Fill').text(fillRate + '%');
        $('#' + weekId + 'Freistellungen').text(data.freistellungen.size);

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

    // Load weekly statistics after all functions are defined
    loadWeeklyStatistics();

  });
})(jQuery);

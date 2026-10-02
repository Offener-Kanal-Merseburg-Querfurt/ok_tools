CHANGELOG
=========

2026-10-02 (Version 4.57.0)
==========================

* **inventory: Track which items carry their barcode label**
  * ``InventoryItem.barcode_attached`` is a checkbox in the change form, next to the location and "available for rental". The admin list shows it as a column and has a filter for it, so the items still waiting for a label are one click away.
  * Two bulk actions mark the selected items as labelled or not labelled.
  * A copied item starts unlabelled: it gets a new inventory number, so its label still has to be printed and stuck on.

* **inventory: New items come with an inventory number**
  * The add form is prefilled with the next free number, continuing the series of the most recently added item, or the first active series when there are no items yet. The number can still be changed before saving.
  * A number passed in the URL is kept. Two people opening the form at once get the same suggestion; the second save is then rejected by the unique constraint.

2026-09-29 (Version 4.56.0)
==========================

* **planung: Ondea learns which broadcaster a programme comes from**
  * Every media item sent to the playout now carries ``sender`` — the media authority set in the license owner's profile (e.g. "OK Dessau"). It is included in the pull endpoint ``GET /api/v1/media`` and in both pushes from the calendar-weeks page ("Send media metadata" and "Send schedule"). Exchange programmes could only be recognised from their description text until now.
  * ``GET /api/v1/media`` returns one item per filename. A file with copies in several storages or versions shares its number, but only one copy carries the license link, so each other copy came out as a second item with the same ``id`` and empty fields. The license is now resolved by number and the filled item wins.
  * ``year`` is unchanged: it is the year the license was created in OK Tools, not a production year.

2026-09-22 (Version 4.55.0)
==========================

* **austausch: An unresponsive storage can no longer take the export worker with it**
  * The video copy to the network share no longer goes through ``shutil.copy2``. That call hands the whole transfer to the kernel, so a CIFS server that stops answering parks the worker in uninterruptible sleep — no timeout, no log line, no way to revoke the task, and a finite ``--concurrency`` that a few such exports exhaust completely.
  * ``austausch.services.file_copy`` copies chunk by chunk (8 MB by default) in a child process whose byte counter the parent watches. A copy that writes nothing for five minutes is killed and the task fails with "Copy stalled", minutes after the storage died instead of days later. A watchdog *thread* cannot do this — only killing the process holding the stuck ``read()`` works.
  * Every chunk reports progress, so the export screen now shows the real percentage and MB/s of the copy. Until now the network-share branch never called the progress callback at all and the bar jumped straight to "100% · 1 of 1".
  * Leftover ``.tmp_`` files older than a day are swept from the export directory before each run. A killed copy never reaches its cleanup handler, so each one used to leave gigabytes behind on a share that is already 96% full.
  * The report distinguishes a missing video file from a storage that does not answer. Both used to read "Video file not found".

* **austausch: The same license cannot be exported twice at the same time**
  * Pressing "Start upload" again queued a second task with identical arguments; both workers then went after the same source file and wrote two different ``.tmp_`` files into the same directory. Items are now locked per export mode in Redis for the duration of the task.
  * A locked item is not an error: it is reported as "already being exported by task …" beside the existing failed and skipped-no-PDF categories, and its row on the confirm screen is greyed out with an "exporting…" tag.
  * The lock takes a short TTL that a heartbeat renews while the task runs, so it neither expires mid-copy nor blocks a license for a day after a crash. Locks whose owning task no longer exists are released by the periodic ``ok_tools.tasks.cleanup_stale_task_results_task``.

* **media_files, austausch: Read from a storage that answers, not from the best one on paper**
  * ``get_quality_score`` puts ARCHIVE 500 million points ahead of PLAYOUT, which no bitrate can outweigh, so the export always read from the archive — even when a byte-identical copy sat on the playout NAS reading at 136 MB/s. The global quality ranking is unchanged; the export now picks its *read source* separately.
  * Only byte-identical candidates count (same file size, and same checksum where both have one), so a different render is never substituted. They are ranked by measured storage health and each one is verified with a short timed read before it is used; the choice is logged, and a fallback is listed in the export report.
  * ``StorageLocation`` gained ``last_read_mbps`` and ``last_health_check``, measured by the hourly ``media_files.tasks.run_auto_scan`` and by every export that reads from a location, and shown in the admin. ``os.path.isfile`` cannot tell a healthy share from a hung one — on the incident behind this change ``stat`` returned instantly while ``read`` crawled at 0.03 MB/s for three days.

2026-09-21 (Version 4.54.0)
==========================

* **inventory: An inventory number holds several devices**
  * ``InventoryUnit`` is one physical device: serial number, status, purchase date and cost, a note. Serial number, purchase date and cost moved off ``InventoryItem`` onto it, and migration ``0045_inventoryunit`` carries the existing data over — one device per item, or one per serial number where an item listed several and its quantity says so.
  * An item's quantity and status follow its devices: the quantity is the number in stock, the status is "in stock" while any device is, "defect" while any is defective, and the way the rest left the stock once none is left. Items without devices keep the quantity and status entered by hand.
  * The item's change form shows the devices and their inspections right under the first fieldset, with quantity and status displayed but not editable while devices exist. An inspection names the device it belongs to, chosen from that item's devices.
  * The Excel export keeps its serial number, purchase date and purchase cost columns, now listing the devices' values. The item import writes the devices instead of the item, and the inspection import assigns an inspection to the device when the item has exactly one.
  * The rental API gains a ``units`` list per item; ``serial_number`` stays as the joined serial numbers of the devices still in the stock, so the wizard and the print forms read as before.

* **inventory: A device can be retired ("Ausgesondert")**
  * A fourth device status beside in stock, defect and written off, for devices sorted out rather than written off the books. An item whose devices are all retired is retired too; a mix of written off and retired stays written off. ``ausgesondert`` in the status column of an import is recognised.

* **inventory, rental: Item and room photos need a login, not staff rights**
  * The photo views were staff only, so the item and room pictures on the rental wizard and the user dashboard stayed blank for the people they are meant for. A signed-in user now sees photos of items offered for rent and of active rooms; staff still see all of them.

* **rental: The wizard's item photos open again**
  * ``openImageLightbox`` in ``wizard.jsx`` is a classic script's top-level function, so it replaced the global of the same name and called itself until the tab froze. It is named ``openPhotoLightbox`` now.

2026-09-19 (Version 4.53.1)
==========================

* **rental: A bare letter ends a location level too**
  * "Fach B" printed its "B" at word size, because a code had to contain a digit. A level now also ends in a code when its last word is one or two letters, optionally followed by digits ("B", "AB", "B12"). Letters count only when they stand apart, so the last letters of a word — "Seminarraum" — are never mistaken for one.

2026-09-19 (Version 4.53.0)
==========================

* **rental: A label says what its format tells it to say**
  * ``LabelLine`` describes a label format row by row — content, size, alignment — and one layout engine (``rental.label_layout``) feeds both the TSPL renderer and the HTML templates, so a format prints the same on paper and on the roll. A format without lines prints the default layout.
  * That default layout is the one asked for: inventory number and owner above the bars, then the description, then the location. It replaces the old order on the roll labels and on the A4 sheet alike.
  * A location prints its shelf codes — the "3" of "Schrank 3" — a whole font size larger than the words beside them, which is what makes a label readable across a room. Installations whose locations carry no such codes turn it off per line.
  * A location that would not fit is shortened rather than cut: first the words are abbreviated ("Schrank" to "Schr."), then levels are dropped from the front, the last level and every code always surviving.
  * The description no longer overprints the owner. The printer's fonts advance about a third wider than their nominal cell, measured on a TE210, and reserving the nominal width made the two columns collide.

* **rental: Roll label type sizes reached the stylesheet unlocalised**
  * The type scale introduced in 4.52.0 passed through Django's localisation, so a German locale wrote ``--fs-desc: 6,0pt`` — not a CSS length. Every font size on a roll label silently fell back to the browser default of 16px.

2026-09-18 (Version 4.52.0)
==========================

* **rental: Any label size, and a print offset for the roll**
  * Label sizes are data now: ``LabelFormat`` holds a name, the millimetres and an optional roll gap, and the print dialog offers every active row. The two sizes the module shipped with are migrated into it under their existing keys, so links already handed out keep working.
  * The barcode geometry and the type scale are derived from the label's millimetres instead of being tuned per format, interpolated through the two sizes that were tuned by hand. A new roll needs nothing but its size entered. The narrow bar widens with the label and narrows again when a long inventory number would otherwise run over the edge.
  * ``label_offset_x_mm`` and ``label_offset_y_mm`` move the printed content away from the edges for a roll that does not sit square under the print head. The offset trims the usable area rather than displacing the finished layout, so moving content away from the top can never push it over the bottom.

2026-09-17 (Version 4.51.0)
==========================

* **rental: Roll labels straight to a network label printer**
  * A TSPL label printer (TSC TE210 and relatives) can be configured in the rental configuration by host, port, resolution, roll gap, density and speed. With a host set, the barcode dialog offers "Send to label printer" for the two roll formats.
  * ``LabelPrinterService`` renders the same layout the roll template prints — description and owner, Code 128 bars, inventory number, location — as TSPL and sends it to port 9100 over a raw socket. ``SIZE`` and ``GAP`` travel inside the job, so no workstation needs a media size, margin or orientation configured, and every machine produces the same label. Text that would not fit is cut to the label instead of running over its edge, and the job selects code page 1252 so umlauts arrive as the printer expects them.
  * ``POST /rental/barcode/print-direct/`` is staff only, takes the printer address from the configuration and never from the request, refuses the A4 sheet formats, and answers an unreachable printer with its address and reason instead of a stack trace.

2026-09-16 (Version 4.50.0)
==========================

* **rental: Roll labels can be printed sideways**
  * ``BarcodePrintView`` accepts ``rotate=90`` for the roll layouts: the ``@page`` size becomes height x width and the label content is turned inside it. Label printers whose media is defined portrait (25 x 51 instead of 51 x 25) rotated the landscape page themselves, which spread a single label over two physical ones.
  * The format chooser in the inventory admin offers the rotation as a checkbox next to the two roll formats, and hides it for the A4 sheet layouts.
  * The roll stylesheet now zeroes the ``html``/``body`` margins for print explicitly, so a browser default margin cannot shift the content off the label.

* **inventory: Drop the leftover ``device_name`` column**
  * Migration 0029 removed ``Inspection.device_name`` from the model, but on databases whose schema came from an older dump the column survived with its ``NOT NULL`` constraint. Django does not write a column it no longer knows, so every insert failed and the admin's "add inspection" page returned a 500. Migration 0044 drops it if it is still there; the data moved to ``target_part`` back in 0028.

2026-08-21 (Version 4.49.0)
==========================

* **notifications: Reel scope is now a setting**
  * ``media_files.missing_reel`` and ``media_files.reel_post_today`` gained a "which broadcasts need a reel" parameter: premieres and repeats with a Mediathek URL (the default, unchanged behaviour) or premieres only. A repeat without a Mediathek URL is still never reported under either choice, because the reel would have nothing to point at.
  * ``ParamSpec`` learned a ``choice`` kind, rendered as a select on the notification settings page and validated against the declared options on save and on read; an unknown stored value falls back to the default instead of reaching the check.

* **tools: Description in the daily reel reminder**
  * The reminder email lists the licence description for every reel, in the text and the HTML body, so the post can be written from the mail itself.
  * The plain text body is no longer autoescaped. Quotes, ``&`` and ``<`` in a description reached the reader as ``&quot;``, ``&amp;`` and ``&lt;``; the HTML body keeps escaping, as it must.

2026-08-20 (Version 4.48.0)
==========================

* **rental: Signature and scanner handling in quick issue**
  * Quick issue opens the same signature dialog the detail page uses once the rental exists, so a scanner-driven hand-over can be signed on the spot. The dialog gained a third option, "sign on paper", which offers the issue slips directly; a rental holding items of several owners lists one slip per owner. Signing stays optional.
  * ``SignatureModal`` moved from ``detail.jsx`` into ``shared.jsx`` so both bundles use one implementation, and the wizard page loads ``signature_pad``.
  * Quick mode no longer accepts a pickup in the past or outside the opening hours: the fields start from the next valid slot, carry a ``min``, and are corrected on blur and on submit. The return is always kept strictly after the pickup.
  * The success/error tone while scanning is now a setting (``RentalConfig.scan_sound_enabled``, **off by default**) instead of always sounding; ``beep`` lives in ``shared.jsx`` and reads the new ``rr-flags`` payload.
  * Signature method cards keep readable text in every state (5.7:1 at rest, 4.5:1 on the filled hover state) instead of grey-on-blue.

* **rental: User category visible wherever a user is picked**
  * ``serialize_user`` classified a rental-only profile as a plain user; it now reports all four categories (employee, member, rental-only, user) in the same order ``RentalConfig.get_organizations_for`` uses, and adds a language independent ``role_key`` next to the label. Every screen fed by that serializer is corrected: the guided user step, the quick picker, the return workflow, the rental detail page and the lists.
  * The quick-mode picker shows the category badge for each match and for the selected user, and its dropdown may grow past its narrow grid cell so name, badge and organization stay readable.

* **notifications: Reels only where a reel has something to point at**
  * ``media_files.missing_reel`` and ``media_files.reel_post_today`` now report premieres (a licence without a contribution) and repeats that already carry a Mediathek URL. A repeat without a Mediathek link produced work nobody could complete.
  * The horizon of the reel check was already configurable as "days before broadcast" (``horizon_days``, default 3) under Notification settings; no change was needed there.

* **notifications: Manual reminders**
  * ``ManualReminder`` holds recurring or one-off reminders staff write themselves, for obligations that leave no trace in the data ("send the TV listings to the newspaper on Wednesday"). They travel through the normal machinery as ``reminders.manual`` events, and the new "Reminders" channel is subscribed to like any other. A monthly reminder configured for a day a month does not have falls on that month's last day.

* **notifications: Delegating an action item**
  * An item can be handed to another staff member. Responsibility moves to exactly one person: the sender's copy is parked in a new "Delegated" view showing who holds it and can be taken back, while the receiver gets a normal open item.
  * A delegated item reaches its receiver even when they subscribe to nothing at all, and the colleague picker lists profile names rather than bare e-mail addresses.

* **planung/licenses: Youth protection broadcast windows**
  * ``YouthProtectionWindow`` configures, per age rating, the window it may be aired in (seeded with 20:00-06:00 for 12, 22:00-06:00 for 16, 23:00-06:00 for 18) and can be switched off per rating.
  * Saving a day plan is refused when a rated item lies outside its window, naming the allowed time; the planner marks the offending row and says so while it can still be moved. Windows and items crossing midnight are handled on a circular clock.

2026-08-19 (Version 4.47.0)
==========================

* **rental: Barcode scanning fixes on the return page**
  * The return page sent the human-readable rental code (``R-2608-0284``) instead of the numeric primary key, so every scan on ``/rental/admin/return/<id>/`` failed regardless of the item. ``api_scan_return_item`` now also rejects a non-numeric ``rental_id`` with a clear 400 instead of raising.
  * Scan errors are shown as text under the field instead of a 500 ms red border, and the input regains focus once the request settles so the next scan needs no mouse.
  * German translations for the scan API responses were fuzzy, wrong ("Item not found in this rental" read as "Diese Ausleihe schließen?") or empty; the return page labels were missing from the i18n bundle entirely.

* **rental: Quick mode is usable with a barcode scanner**
  * The user ``<select>`` listing every account is replaced by a type-ahead picker sharing the guided step's search (local list plus debounced ``api_users_search``), so users outside the preloaded list are findable. Enter picks a single match and moves focus to the scan field.
  * Scanned items show their full availability status — In stock / Booked / Reserved / Issued plus reserved and issued counts — so an item wrongly left in "issued" state is visible at scan time. The badge logic is shared with the guided catalog.
  * Quantities can be changed in place with +/− instead of only removing the row.

* **rental: Return receipt email was sent in English**
  * ``rental_return_receipt_*`` templates fell back to their English msgids because every entry was fuzzy or untranslated in the German catalog.

* **ok_tools: Recover Celery tasks whose worker disappeared**
  * A worker restarted mid-task (deploy, OOM) never writes a terminal state, leaving ``TaskResult`` in PROGRESS forever. ``ok_tools.celery_health`` asks the live workers which task ids they hold and closes the rest as FAILURE with an explanatory traceback, also closing any ``ExportToServerRun`` left open by the same task.
  * Runs from Celery beat (``cleanup_stale_task_results``, ``CELERY_BEAT_CLEANUP_STALE_TASKS``, every 15 minutes) or manually via ``manage.py cleanup_stale_tasks [--dry-run]``. Thresholds: ``CELERY_STALE_TASK_MINUTES`` (default 60) and ``CELERY_STALE_TASK_HINT_MINUTES`` (default 15).
  * When no worker answers the inspect ping the sweep is skipped, so a transient broker outage never fails running tasks.
  * The Celery admin shows "Interrupted (worker gone)" instead of a neutral "In progress", and the export status API/result page report the run as interrupted instead of polling forever.

* **austausch: Precise export error messages**
  * The Planung and license-number modes now name the date range, the license numbers that failed the media authority / exchange flag filter, and the numbers that were already exported, instead of one generic "No licenses match" for every cause.

2026-08-18 (Version 4.46.0)
==========================

* **licenses: Automatic Nextcloud downloads**
  * A file uploaded to Nextcloud is fetched into local storage on its own, using the same path and naming as the manual Download button (``LicensesConfig.download_storage_path``, ``<number>_<filename>``). The new ``auto_download_to_storage`` switch in Storage Settings turns the automation off.
  * Each file is downloaded exactly once. ``NextcloudVideoFile`` records the download time and local path; moving or deleting the local copy afterwards never triggers a second download. Repeats stay a manual decision — the admin buttons force a fresh download.
  * A catch-up task (``licenses.tasks.download_pending_nextcloud_videos``, beat ``CELERY_BEAT_DOWNLOAD_PENDING_NEXTCLOUD_VIDEOS``, every 20 minutes) queues uploads whose signal was missed, e.g. while the download worker was down. Migration ``0029`` marks pre-existing files as handled so the archive is not pulled in bulk.
  * Downloaded photos no longer create a ``VideoFile`` in media_files, and the license list shows them as "Nextcloud Photo".

* **licenses: Photo upload for screen boards**
  * A license marked as screen board (Bildschirmtafel) accepts photos (jpg, jpeg, png, webp) in addition to videos. The upload dialogs in the license list, the "license created" modal and the update page switch to photo mode automatically.
  * ``ConfirmUploadView`` now validates the file extension against what the license accepts; previously any file type was recorded.

2026-08-17 (Version 4.45.0)
==========================

* **rental: Safer room scheduling and period changes**
  * Past room slots are visually distinct and cannot be selected, while occupied calendar blocks link directly to the rental detail.
  * Period edits validate working hours plus room and inventory conflicts before atomically synchronizing the rental and its room reservations.

* **austausch: Recover imports after remote metadata outages**
  * API-backed channels fall back to synchronized ``meta.json`` metadata when the remote endpoint is temporarily unavailable.
  * Failed feed and admin imports can be retried, and a later completed attempt automatically resolves the earlier notification.

* **notifications: Report missing covers only for premieres**
  * Licenses with an existing contribution are treated as repeats and no longer create missing-cover action items.

2026-08-13 (Version 4.44.2)
==========================

* **deployment: Production update fixes found while restoring TLS**
  * ``nginx`` renders its configuration again under the custom reload command. The image entrypoint runs ``/docker-entrypoint.d/*`` only when its first argument is literally ``nginx``, so the ``/bin/sh`` command introduced in 4.44.1 silently skipped the template rendering and nginx came up on the stock config - no TLS listener, no ACME location. The command now execs ``/docker-entrypoint.sh nginx``.
  * ``update.sh`` no longer aborts while copying an unchanged nginx entrypoint script. ``deployment/`` is root-owned from the installer, so the copy fell through to an unguarded ``sudo`` that could not prompt for a password, and ``set -e`` killed the run mid-update. The copy is skipped when the files already match, sudo is used only when it works without a prompt, and the failure path names the ``chown`` that fixes it.
  * Requests with an unknown ``Host`` are refused by nginx instead of reaching Django. Scanners hitting the bare IP produced a 400 ``DisallowedHost`` traceback per request; a ``default_server`` now answers 444 and rejects the TLS handshake rather than presenting the certificate.

* **registration: MediaAuthority default no longer churns migrations**
  * ``MediaAuthority.name`` used ``default=settings.OK_NAME_SHORT``, which makemigrations freezes into the migration as a literal. Each installation therefore recorded its own value (``0009`` holds ``OKMQ``, ``0014`` holds ``OK Merseburg``) and made every other installation report unapplied model changes. The default is now a module-level callable, serialized as a stable function reference while the value is still read from settings at runtime. The accompanying ``AlterField`` does not alter the database schema.

2026-08-13 (Version 4.44.1)
==========================

* **deployment: Keep the TLS certificate renewing without supervision**
  * ``certbot`` now restarts with ``unless-stopped`` like every other service. The entire renewal schedule is a loop inside that container, so when it exited in June 2026 renewal stopped silently and the production certificate expired; it was the only service in the compose file without a restart policy.
  * ``nginx`` reloads itself every 6h. It reads the certificate once at startup and keeps it in memory, so a renewed file on disk was not actually served until the container happened to restart. A certbot ``--deploy-hook`` cannot do this instead: it runs inside the certbot container, which has no route to the nginx process short of mounting the docker socket.
  * ``diagnose.sh`` now reports stopped services and the expiry of the certificate actually served on port 443. ``docker compose ps`` without ``-a`` lists only running containers, so the dead certbot was missing from the output rather than flagged as a problem.

2026-08-13 (Version 4.44.0)
==========================

* **notifications: One way into the centre, and a link that does the work**
  * Removed the daily summary block from the admin start page. The header bell and the ``Benachrichtigungen`` menu entry are the two entry points; a third copy of today's list only repeated the bell and pushed the module menu down the page.
  * "Planned own production without a reel" now offers the Reel Studio prefilled from the license — title, author, category, description, duration, broadcast day/time and the source video — instead of only naming the number. The link appears as an action in the row and as the primary button in the detail drawer.
  * The prefill moved out of the license admin into ``licenses/reel_prefill.py`` and is shared by the admin action, the change-form button and the notification, so all three land on the identical form. It is built while reading, never stored, because the broadcast date and the source video can change after the event was written, and it stays empty when the Reel Studio is not configured.

2026-08-11 (Version 4.43.0)
==========================

* **rental: Sortable rental list headers**
  * Rental ID, project/user, time, derived status and combined inventory/room counts can be ordered in either direction for every status view.
  * Status tabs, search, user/content filters and pagination preserve the selected ordering; query parameters are validated against an explicit allowlist.

2026-08-11 (Version 4.42.0)
==========================

* **notifications: Human-attention workflow instead of a system activity feed**
  * Normal automation no longer creates work: discovering or indexing a video and successful slideshow/audio jobs stay silent. Orphan files are checked only in explicitly selected storage locations and wait for the automatic-linking grace period; confirmed licenses wait for uploads and indexing, and missed broadcasts allow a configurable playout delay.
  * Rental obligations now follow the real lifecycle. New draft requests require confirmation, today's pick-ups and returns exclude old appointments, missed pick-ups become a separate action, and today's confirmed room bookings remind staff that somebody has to be present. Confirmation, issue resolution, issue/return completion or rescheduling close the corresponding task from current model state.
  * The license/media/planning chain exposes only the current blocker: confirmation precedes a manual Nextcloud download, a pending upload suppresses the generic missing-video reminder, an approaching committed plan owns the urgent missing-video task, Live contributions bypass file assets, and Cover/Reel checks start only when their prerequisites hold. Ready reels create a manual posting task on their broadcast day.
  * Stored action and problem events now resolve automatically across Rental, licenses, media operations, storage, Austausch, Planung, tools, registration and Celery. A successful retry closes the corresponding failure; repeated scans keep one active row per condition; aging entries escalate the original confirmation/verification task instead of duplicating it.
  * Added active-storage-unavailable detection. An unreadable NAS path is now a visible technical problem instead of merely producing a log warning, while the Problems overview counts only incidents whose cause still exists.
  * Added focused lifecycle coverage; the notifications suite now contains 88 passing tests. German catalogue remains fully translated.

2026-08-09 (Version 4.41.0)
==========================

* **notifications: Interactive React notification center**
  * Replaced the server-rendered feed with a responsive React work surface matching the rental process UI, including rich event rows, payload details, a bottom detail drawer and a prominent expectations panel.
  * The five overview cards are interactive table filters for today's live expectations, new events, open actions, postponed items and problems. Expectations remain derived at render time and are exposed as read-only rows rather than stored events.
  * Notification links now open the affected object or a narrowly filtered working screen. Rental entries open the specific request, exchange entries search for the exact file, and license/media/planning entries retain object- or date-specific targets.
  * Added the notifications JSX target to the production build pipeline; generated bundles remain untracked, are included in the Docker build context and are collected with the other static assets during deployment.
  * Corrected failed media-operation signal handling for the model's uppercase status values and expanded German UI translations and focused regression coverage.

2026-08-09 (Version 4.40.0)
==========================

* **notifications: New app — daily summary and event feed in the admin (stage 1: framework)**
  * Delivery is the rendering of a page, not a mailing: no emails, no polling, no websockets. A summary block appears at the top of ``/admin/``, a bell in the header carries the count of open action items, and ``/admin/notifications/`` holds the full feed.
  * Facts and expectations are kept apart. A fact ("license created", "video uploaded") is stored in ``NotificationEvent``; an expectation ("equipment due back today") is derived from current data, recomputed on render and cached for five minutes. Expectations are never stored, so moving a date never leaves a stale row behind.
  * ``digest_time`` (10:00 by default) is a marker for the day, not a send time. The Celery task produces the events no signal can produce and refreshes the expectations; the schedule is synchronised into django-celery-beat from ``NotificationConfig``, so the time can be changed in the admin without a deployment.
  * Event types are declared in ``notifications/event_types.py`` and mirrored into the database after ``migrate``. Adding a type — including its parameters, rendered as number fields on the settings page — needs no migration.
  * Three gate levels that are never mixed: the module flag in settings, the per-channel switch in the settings page, and the personal subscription. A disabled check is not executed at all, and a subscription cannot re-enable it.
  * Visibility mirrors the admin itself through ``ModelAdmin.has_view_permission`` instead of ``user.has_perm``, because three admins in this project grant on ``is_staff`` regardless of permissions and ``tools`` requires a superuser. A subscription can therefore never widen access.
  * Subscription presets (Verleih, Redaktion, Technik, Verwaltung) tick a set of checkboxes; they are not Django groups and grant nothing. Subscribing backfills the action items that are still open.
  * Event text is rendered from ``payload`` at read time in the reader's language, never stored as a string. Every event carries a ``dedup_key``, so a repeated scan or a doubled signal creates nothing.
  * The catalogue covers twelve event types across six modules, added without a single migration because the types are declared in code:
    * **rental** — equipment to hand out today, equipment due back (both expectations), and equipment overdue. The overdue check has a grace period and re-raises the entry on a fixed interval instead of daily, by putting the escalation bucket into the deduplication key.
    * **licenses** — a new unconfirmed license (signal), one unconfirmed for too long (scan), and a video an author uploaded to Nextcloud that is still not on a storage location. The last one matters because the download task is only ever started by hand from the admin.
    * **media_files** — a video the storage scan picked up, skipping rendered reels (`is_preview`).
    * **austausch** — exchange material discovered but never imported, limited to a configurable window.
    * **planung** — no plan for one of the coming days (or an empty one), and planned entries whose license has no available video file. Both read `TagesPlan.json_plan` directly instead of the playout API.
    * **registration** — a new profile awaiting verification (signal) and one waiting for too long (informational).
  * Every threshold is a parameter on the settings page rather than a constant: waiting days, grace period, escalation interval, look-ahead horizons and discovery windows.
  * The catalogue grew to twenty-four types with the technical production events:
    * **media_files** — a video whose resolution or frame rate deviates from the configured encoding preset (never a hard-coded 1920x1080/25; ``fps`` is compared with a tolerance because ffprobe reports 24.999 for correct material), an own production scheduled soon without a reel, the same without a cover, a video that could not be linked to a license, a failed render/transcode/copy job, and a storage location running out of space.
    * **licenses** — a confirmed license that still has no video file and therefore cannot be planned.
    * **rental** — damage or a defect recorded on a rental.
    * **austausch** — a download or import that ended with an error.
    * **planung** — a scheduled entry the playout never started.
    * **tools** — a finished slideshow or audio job, addressed to whoever started it rather than to the module subscribers (``emit(recipients=...)``).
    * **system** — failed background tasks, grouped by task name so a permanently broken task cannot fill the page. Superuser only.
  * Reel and cover are two separate event types on purpose: a channel may produce covers but no reels, and one combined type could not be switched off halfway.
  * **New field ``OrganizationConfig.media_authority``** with a data migration seeding it from ``ExchangeConfig.default_media_authority``. Which "Offener Kanal" an installation is belongs to the organization, not to the exchange module — a channel may not use the exchange at all. The reel and cover checks report nothing while it is unset rather than treating other channels' material as own productions.
  * Notifications link to the screen the work actually happens on, not to the admin change form: rental entries open ``/rental/admin/rental-process/``, exchange entries open ``/austausch/feed/`` filtered down to the file, and planning entries open ``/admin/planung/tagesplan/calendar-weeks/`` on the affected day. Those three modules are not operated through the standard changelists, so a change-form link would send people to a page they never use.
  * Shared lookups moved into the apps that own the data instead of being copied a fourth time: ``planung.selectors`` (what is planned, and when) and ``media_files.utils`` (numbers with a video, a reel or a cover; the target encoding preset; the format deviation). ``austausch.views._license_has_cover`` now delegates to the shared helper.
  * **Adoption report** at ``/admin/notifications/stats/`` (superusers) and as ``manage.py notification_stats [--days N] [--json]``. It answers the two questions the feature stands or falls on — is the page read, and do the items get closed — from data that is already recorded: the read marker, the dismissal and snooze timestamps and the suppressions. Nothing extra is tracked about people. Per event type it shows events, items, handled, open, postponed, silenced and the median hours to close; per staff member the subscriptions, the last visit and the workload. A type with many silenced entries and few handled ones is reporting the wrong thing; a type with no events over a long window either is switched off or asks a question this channel does not have.
  * New setting ``NOTIFICATIONS_ENABLED`` (default on) and a cleanup task honouring ``retention_days`` (90 days by default).
  * Filters, bulk actions and permanent silencing on the notifications page. A periodic check re-raises the same finding in the next period, which is right for a deadline and wrong for the 122 old licenses that will never be confirmed. The page now filters by module, event type, date range and "older than N days", selects either the ticked rows or everything matching the current filter, and offers two different actions: **Als erledigt markieren** (personal, one event) and **Nie wieder melden** (global, creates a ``NotificationSuppression`` so ``emit()`` never recreates the event for that object). Suppressions are listed and revocable in the admin for superusers. The action list is paginated at 50 rows.
  * Subscriptions moved to their own page at ``/admin/notifications/subscriptions/``, linked from the toolbar and the admin menu. They are set once while the notification page is opened every day, so the checkbox matrix of every module was permanent clutter on a screen that should be about today.
  * The page is **one list in four states** (`?view=open|snoozed|handled|all`) instead of an action list plus a separate chronicle. The chronicle without actions was the reason a page could look full of entries and offer nothing to do with them; it is now the "all" state of the same list, with the same bulk actions. Every row shows its personal state, so a finished list says "handled" rather than looking actionable. The actions follow the state — open offers handle and postpone, postponed offers wake and handle, handled offers **reopen** — while silencing is offered everywhere because it concerns the object, not the task. Marking as handled is now reversible.
  * **Postpone until tomorrow** for action items. ``snoozed_until`` is set to tomorrow at ``NotificationConfig.digest_time``, so the entry comes back for the next summary rather than after an arbitrary 24 hours. Postponed entries are listed under ``?snoozed=1`` with a count next to the heading and can be brought back immediately; on that view "select all" addresses the postponed rows, since the open list is empty there by definition.
  * Open action items now follow the subscriptions instead of only what was once assigned, so unsubscribing from a module empties its counter and re-subscribing restores the open items through the backfill.
  * German translations for all 232 strings of the app. The partials rendered by the ``ok_tools`` template tags live inside the app, so their strings belong to ``notifications/locale`` and ``ok_tools/locale`` stays untouched.

2026-08-09 (Version 4.39.0)
==========================

* **rental: Close unauthenticated and cross-user access on the rental endpoints**
  * ``api_issue_from_reservation`` and ``api_get_all_equipment_sets`` were reachable without logging in; the first one moved a rental to ``issued``, wrote transactions and added items. Both now require staff, like every neighbouring endpoint.
  * The DRF viewsets for rental requests, rental items and rental issues filter by owner: a non-staff account only sees its own records instead of every rental in the database.
  * ``created_by`` and ``status`` became read-only on ``RentalRequestSerializer``, and ``perform_create``/``perform_update`` pin ownership, so a borrower can no longer promote a reservation to ``issued`` or hand it to another account. Status transitions stay with the workflow endpoints that also write the matching ``RentalTransaction`` rows.
  * ``SaveSignatureView`` and ``CreateSigningSessionView`` now check that the caller is staff or the borrower; previously any logged-in user could forge or wipe the signature on any rental request by guessing its id.
  * Removed ``@csrf_exempt`` from ``api_update_pick_list`` (the caller already sends ``X-CSRFToken``) and stopped returning tracebacks from ``api_inventory_calendar``.
* **rental: Rebuild signature SVGs from a whitelist**
  * ``_sanitize_signature_svg`` parsed the payload with a list of forbidden strings and stored the original text, which is rendered with ``|safe`` on the admin change form. Event attributes outside that list (``onbegin``, ``onmouseover``, ``onclick``) passed straight through.
  * The payload is now parsed with ``defusedxml`` and rebuilt from an allowed set of elements and attributes covering what ``signature_pad.toSVG()`` emits, so nothing executable survives and XXE is blocked.
* **media_files: Escape scanned filenames in the version admin**
  * Filenames come from scanning the video storage and were interpolated into HTML with f-strings before ``mark_safe``. Switched to ``format_html``.
* **deployment: Harden the production settings and container**
  * Added ``SESSION_COOKIE_SECURE``, ``SESSION_COOKIE_HTTPONLY``, ``SECURE_SSL_REDIRECT`` (overridable, with ``/health`` exempt so the Docker healthcheck keeps working) and HSTS to the ``USE_SECURE_SETTINGS`` block. ``CSRF_COOKIE_HTTPONLY`` is deliberately left off because the frontend reads the token from the cookie.
  * ``install.sh`` and ``update.sh`` write ``DJANGO_USE_SECURE_SETTINGS`` while settings read ``USE_SECURE_SETTINGS``, so the whole block was inactive on script-installed hosts. Both spellings are accepted now.
  * ``production.Dockerfile`` gained ``USER app``: the web container ran as root while the celery services already dropped privileges. **Requires an image rebuild to take effect.**
  * The web service publishes on ``127.0.0.1:8010`` instead of every interface, and nginx restricts ``/prometheus/`` to private networks.

2026-07-23 (Version 4.38.0)
==========================

* **rental/inventory: Carousel lightbox for multi-photo items and rooms**
  * The photo lightbox now pages through all photos of an item or room with on-screen arrows, a counter, and Left/Right keys; a single photo behaves as before (no controls shown).
  * Unified on one ``rental/js/lightbox.js`` (carousel, per-slide caption and "Original" link, JSON-array and ``data-lightbox-group`` support). The inventory admin's separate ``photo_lightbox.js`` was removed and both the inventory and room admin now load the shared script.
  * Every surface passes the full photo list: inventory admin list column and change-form gallery, room admin inline, the rental process wizard (items and rooms), the room calendar day/week/month, and the inventory calendar day.

2026-07-23 (Version 4.37.0)
==========================

* **rental: Zoom room and inventory photos across rental pages**
  * Room photos now open in a full-screen lightbox everywhere, matching how inventory item photos already zoom: on the rental process wizard (room cards) and across the calendars.
  * Added a shared ``rental/js/lightbox.js`` (``window.openImageLightbox`` plus a ``data-lightbox`` click delegation) used by the room calendar week/month and the inventory calendar day templates; the room calendar day timeline and the wizard call it from React.
  * Views expose full-size image URLs (``image_full_url`` / ``full_url``) alongside the existing thumbnails, so a small tile loads the thumbnail and the lightbox loads the full image.
* **rental: Localize the room calendar day page**
  * ``RoomCalendarDayView`` now emits the ``rr-i18n`` bundle the shared JS reads, and the bundle gained the room-calendar keys, so the day timeline (and the zoom tooltip) render in German instead of English fallbacks.

2026-07-23 (Version 4.36.0)
==========================

* **inventory: Photo lightbox and downscaled previews**
  * Item photos in the admin (list column and change-form gallery) open in an in-page lightbox that preserves aspect ratio, instead of a new tab; a modifier/middle click still opens the full original.
  * Added a ``preview`` image derivative (longest edge ~1600 px) served by ``serve_item_image_preview``; the lightbox loads it rather than the multi-megapixel original, so the modal opens fast. Thumbnail and preview are cached side by side.
* **rental: Serve room photos through a view (nginx-on-another-VM fix)**
  * Room photos are streamed by the staff-only ``serve_room_image`` view instead of a static ``/media/`` URL, which 404s when nginx runs on a separate VM without the app's media folder. The admin preview and the file widget's "Currently" link both go through the view.
  * ``?size=thumb`` returns a cached, downscaled JPEG so calendars and previews do not download full-resolution room photos.
* **rental: Photo previews across the calendars**
  * The room calendar (day timeline, week and month) shows a room thumbnail next to each room; the inventory calendar day view shows an item thumbnail next to each item.
* **rental: Working dashboard filters**
  * The rental list filters now apply: a room/inventory content filter and a user-category filter whose categories (users, members, employees, rental-only) mirror ``RentalConfig.get_organizations_for``. Status tabs preserve the active filters; the dead date-range dropdown was removed.

2026-07-21 (Version 4.35.0)
==========================

* **rental: Roll label formats for barcode printing**
  * Added ``BARCODE_LABEL_FORMATS`` to ``BarcodePrintView``: the two A4 sheet layouts plus two thermal roll layouts (51 × 25 mm and 70 × 32 mm) rendered by the new ``barcode_print_roll.html`` template with a matching ``@page`` size.
  * Each format carries its own ``SVGWriter`` options (module width/height, quiet zone); the inventory number is printed by the template, so python-barcode no longer repeats it under the bars.
  * ``BarcodeService.generate_svg`` accepts writer options and adds a ``viewBox`` to the generated SVG, so a barcode scales into its CSS box instead of being cropped.
  * Labels now also show location and owner; the admin barcode modal offers the four formats as radio buttons and got German translations.
* **rental: Scan panel on the return screen**
  * The return screen renders the barcode input with green/red border feedback and a returned/total progress counter, so an operator can work without looking away from the counter.
* **inventory: Photo thumbnail column in the item list**
  * The admin item list shows a photo thumbnail (linking to the full-size original) in place of ``inventory_number_owner``; the column is hidden while ``InventoryImageConfig`` is disabled and uses the prefetched images, so no extra query per row.
* **inventory: ``link_inspections`` deprecated**
  * The command is now a no-op that only reports the number of unlinked inspections: inspections are linked during import because the inventory number is the foreign key column itself.
* **licenses: Deterministic broadcast date fallback**
  * The ``TagesPlan`` fallback in ``LicenseMetadataSerializer`` is ordered by date, so the earliest planned broadcast wins when a license appears in more than one plan.
* **projects: Explicit ICS content type**
  * The ICS export sets ``text/calendar`` explicitly instead of relying on the host mime type database.
* **chore: Test suite maintenance**
  * Added ``pytest-timeout`` with a 300 s per-test timeout to guard against wedged database teardown hanging a run.
  * Added an inventory ``conftest.py`` that restores the seeded default inventory number series, which transactional browser tests flush from a reused test database.
  * Revived and fixed tests across contributions, inventory, licenses, projects, registration, rental and ok_tools; added ``pdfFormFields`` to ``ok_tools.testing`` for asserting on pdftk-filled acroform values.

2026-07-12 (Version 4.34.0)
==========================

* **austausch: Reuse existing cover on export to server**
  * Export to server now prefers the already-created canonical cover (``{number}_cover.jpg`` in the cover output dir, the same file shown as "Cover present" on export step 2) and only auto-generates one into the hand-off directory when none exists, instead of always regenerating.
  * Cover load/generation/upload problems can no longer fail an otherwise-successful export (cover is optional).
  * The export result page reports licenses whose cover was auto-generated (no cover existed) via a new counter card and an ID list; ``ExportToServerRun.details`` carries ``covers_generated``.
  * Fixed the result page reloading endlessly after completion: the progress bar and its polling script now render only while the run is not yet finished.

2026-07-08 (Version 4.33.0)
==========================

* **media_files: Configurable render encoding preset**
  * Added ``MediaFilesConfig.render_encode_preset`` so the "Render video" admin actions (standard, preview, intro/outro) no longer hardcode ``1080p25_9000k``; the output bitrate now follows the selected preset (``tools.VideoEncodePreset`` row or JSON), independent of the HEVC transcode preset.
  * Consolidated the HEVC transcode fallback to the ``EncodePreset`` dataclass defaults instead of a duplicated literal dict, removing the stray hardcoded bitrate.
  * Added German translations for the new config strings.
* **inventory: Index photos placed directly in the base folder**
  * ``scan_inventory_images`` now also indexes photos named after the inventory number directly under ``<base>/`` (e.g. ``OK-000001.png``), with an ``_`` suffix for multiple photos (``OK-000001_1.png``), alongside the existing ``<base>/<inventory_number>/`` layout.
* **rental: Fix room booking times shown without timezone**
  * Room booking start/end times on the rental detail page are now converted to the local timezone before display, matching how input is interpreted on save.
* **licenses: Skip staff signature for non-approved Freistellung**
  * The confirming staff member's signature is only overlaid on an approved (genehmigt) Freistellung, not on a non-approved one.

2026-07-06 (Version 4.32.0)
==========================

* **inventory: Item photos from a mounted folder**
  * Added ``InventoryImageConfig`` (singleton) to point at a mounted photos folder (an existing Media Files ``StorageLocation`` or a manual path) and ``InventoryItemImage`` to index photos found under ``<base>/<inventory_number>/``.
  * Added a ``scan_inventory_images`` management command and periodic Celery task that index images, generate cached JPEG thumbnails (Pillow), and detect missing files; thumbnails can be cached under ``MEDIA_ROOT`` or beside the originals.
  * Admin change page shows a photo gallery with an SVG placeholder; staff-only views serve originals and thumbnails from outside ``MEDIA_ROOT`` with path-traversal protection.
* **rental: Item and room photos on the frontend**
  * ``RentalConfig`` gained ``show_item_photos`` and ``show_room_photos`` toggles (default off).
  * Item search payloads (rental process wizard and user dashboard) include thumbnail and full-image URLs; photos render inside existing card layouts with a click-to-enlarge lightbox.
  * Added ``RoomImage`` with admin upload/inline; room photos display in the rental process room picker.
  * Dashboard quantity controls are hidden for single-quantity items and made legible for multi-quantity items.
* **chore: Fixed inventory import FileField storage migration drift**
  * ``tmp_import_storage`` is now a callable so migrations no longer bake the environment-specific ``gettempdir()`` path.

2026-07-03 (Version 4.31.0)
==========================

* **rental: Persist automatic return reminder state**
  * Added `RentalRequest.auto_return_reminder_sent_at` so scheduled return reminders are sent once per issued rental.
  * Reset the marker when reminder delivery fails so the next scheduled run can retry.
* **licenses: Stop periodic Mediathek not-found retries**
  * Periodic Mediathek refresh jobs now skip Celery retries when PeerTube has no matching video yet.
* **deployment: Include dedicated Celery workers in media mounts**
  * Updated generated override defaults so NAS and custom media mounts include copy, render, download, and anchor render workers.

2026-07-02 (Version 4.30.0)
==========================

* **licenses: Periodic Mediathek URL refresh**
  * Added separate daily Celery beat tasks for planning and contribution broadcast data to queue missing Mediathek URL refreshes.
  * Registered the tasks with `setup_periodic_tasks` and German admin display names.
* **tools: Reel reminder Mediathek URL handling**
  * Reel reminder emails now retry missing Mediathek URLs for up to one hour before sending with a visible warning.

2026-07-01 (Version 4.29.0)
==========================

* **tools: Send daily Reel Studio reminder emails**
  * Added configurable daily reminder emails with signed 24-hour public download links for generated reels.
  * Prefill Reel Studio from license and planning metadata, including source video, broadcast date, and broadcast time.
* **deployment: Isolate copy and anchor render Celery queues**
  * Routed video copy jobs and anchor render chains to dedicated `copy` and `anchor_render` queues.
  * Added production worker services and environment variables for copy and anchor render concurrency.

2026-06-28 (Version 4.28.0)
==========================

* **tools: Send title and optional kicker in the reel beitrag**
  * `/api/reel` now receives `beitrag.titel` (shown title) and an optional `beitrag.sendung` (kicker); Reel Studio adds a "Sendung (Kicker)" field and the license action prefills it from the category
* **media_files: Cover overlay "draw title" toggle**
  * `CoverOverlay.draw_title` lets an overlay skip the license title (e.g. when the graphic already contains text or the cover type renders without a title); migration 0029

2026-06-28 (Version 4.27.0)
==========================

* **tools,licenses,media_files: Improve Reel Studio media selection**
  * Reel Studio now offers Media Files number search and accepts the `sachlich` hook type.
  * License admin Reel Studio actions ignore generated reel files when choosing the source video and omit `video` prefill when no full source exists.
  * Finished reels are registered as `VideoFile.is_preview=True`, and storage scans classify `*_Reel_*` files as preview clips so they do not count as full versions.

2026-06-26 (Version 4.26.1)
==========================

* **tools: Fix reel source path dropping storage subfolders**
  * `share_relative_path` now derives the path inside the CIFS share from the StorageLocation UNC (`\\host\Share\000_Sendungen` -> `000_Sendungen`) and builds `<prefix>/<storage subpath>/<file_path>`, so playout videos keep folders like `000_Sendungen` (e.g. `playout/000_Sendungen/2026_KW_27/...`) instead of being sent as `playout/2026_KW_27/...`; archive paths (storage at share root) are unchanged

2026-06-26 (Version 4.26.0)
==========================

* **media_files: Cover / thumbnail generation subsystem**
  * New `media_files.covers` package builds 16:9 cover images (`{number}_cover.jpg`) from a video frame plus license metadata (title, author, category, episode number); entry point `generate_cover` / `generate_cover_for_license`, resolver picks a template + theme, renderer composites the result.
  * `CoverTemplate` (**Cover-Vorlagenregeln**) — admin rules selecting a template (`base`, `journal`, `trailer`) by series (regex on title), category (regex on category name), or channel default, evaluated by priority with optional theme overrides.
  * `CoverOverlay` (**Cover-Grafiken**) — uploadable PNG/SVG overlays grouped into pools, with configurable text/logo areas, accent color, and per-overlay toggles (`use_video_frame`, `darken_frame`, `draw_logo`, `draw_title`).
  * `CoverOverlayRule` (**Cover-Grafikregeln**) — map a title/category pattern to an overlay pool or explicit graphics, in `random` (one stable pick per number) or `all` (variants + contact sheet) mode; graphic rules take precedence over template rules.
  * `MediaFilesConfig` gains cover fields (`cover_enabled`, logo, title/body fonts, category colors, template rules, output storage/subdir/dir); migrations 0022–0027.
  * License admin actions "Cover-Bild erzeugen / neu erzeugen" and "Cover-Varianten erzeugen & auswählen…" with a candidate variant gallery and frame/timecode picker; all gated behind `cover_enabled`.
  * Wired into the Austausch export-to-server flow: a cover is auto-generated into the export hand-off (thumbnail) directory so exchanged content always ships with a thumbnail.
  * New `generate_covers` (bulk) and `pick_cover` (promote a candidate) management commands; German translations for all new strings.
* **tools: Reel Studio — broadcast-date filenames and reel preview/download**
  * Output filename now uses the broadcast date from `planung` (latest plan containing the license) instead of today; falls back to today when unplanned
  * Finished reels can be viewed and downloaded: new `reel_output_stream` view (HTTP Range + `?download=1`) and a player with View/Download links after rendering
  * `ToolsConfig` gains `reel_output_storage` (defaults to the first Playout storage) and `reel_output_subdir` (`003_Programmvorschau`); `resolve_reel_output_file` resolves the rendered file safely
  * Requires the playout share to be mounted in the web container for preview/download
* **i18n: German translations for the new strings**

2026-06-26 (Version 4.25.2)
==========================

* **licenses: Reel Studio picks the playout video copy, then archive**
  * `LicenseAdmin._reel_video_file` ranks a license's available video files by share (playout before archive before other), newest first, and uses it for both the prefilled path and the inline player; falls back to the primary video file

2026-06-26 (Version 4.25.1)
==========================

* **tools: Reel Studio — share-relative video paths, model warm-up, longer timeout**
  * Video paths now carry the renderer share prefix (`playout/` = Sendedaten, `archive/` = FilmArchiv) derived from the file's StorageLocation, instead of a bare filename
  * `ReelStudioView` triggers a best-effort, non-blocking model warm-up (`/api/hook/warmup`) on page open so the first hook generation is warm
  * `ToolsConfig.reel_render_timeout` default raised 30 → 360 (and applied to hook requests) so a cold AI model is not cut off before the renderer responds
  * Note: gunicorn `timeout` should be >= 360 on the server (config file is deployment-managed; set `GUNICORN_TIMEOUT=360`)

2026-06-26 (Version 4.25.0)
==========================

* **celery: Isolate long Nextcloud downloads**
  * Added a dedicated `download` queue and production `celery_download_worker` with concurrency `1` by default
  * Routed Austausch exchange-file downloads and license Nextcloud video downloads to the `download` queue so long transfers no longer occupy the general-purpose worker pool
  * Updated deployment override generation so NAS/custom mounts are also applied to the download worker
* **admin: Make Celery task filters readable**
  * TaskResult and PeriodicTask admin filters now use the same human-readable task labels as the task-name columns while preserving the original query parameters
* **media_files,tools: Force H.264 Level 4.1**
  * FFmpeg render, slideshow generation, and HEVC-to-H.264 transcode commands now pass `-level:v 4.1` explicitly to avoid encoder auto-selection of higher H.264 levels
* **tools: Add Reel Studio integration (external OKMQ reel renderer)**
  * New tool at `/tools/reel-studio/` to generate AI hooks and render short vertical reels via the external renderer (`/api/hook`, `/api/cta`, `/api/reel`); all calls run async through Celery tasks with `AsyncResult` polling (no gunicorn-blocking sync calls)
  * New client `tools/services/okmq_reel.py` reads config from `ToolsConfig` and encapsulates the `hook_type` (snake) → `hookType` (camel) mapping
  * `ToolsConfig` gains `reel_studio_enabled` + URL/API key/timeout/output-name pattern/mediathek defaults; `is_reel_configured()` gates the tool card, page and license admin action (mirrors the `cover_enabled` pattern)
  * AJAX endpoints `api/reels/{hooks,cta,render,tasks}/` (staff-only, 404 when the service is not configured)
  * Operator page (admin look) with an inline video player to pick the start second manually when opened with `video_id`
* **licenses: Add "Reel erstellen" admin action and per-object button**
  * Bulk action + button on the license change page open the Reel Studio prefilled (video path, title, output name, author from profile, and TV day/date + time looked up from the latest `planung` plan containing the license)
  * Hidden when the reel service is not configured
* **i18n: German translations for all new Reel Studio strings**

2026-06-24 (Version 4.23.1)
==========================

* **rental: Fix QR signature flow blocked by case-sensitivity mismatch**
  * `rental/static/rental/js/detail.jsx` compared the poll status to uppercase `'SIGNED'` while the backend returns lowercase `'signed'`, so the main browser stayed on "Waiting for signature…" forever; status is now matched case-insensitively
  * After the phone submits, the main browser shows an explicit "Signature received" state (~1.8s) before reloading, then the Signed badge appears and the request-signature button is hidden
* **rental,licenses: Improve mobile QR signature UX**
  * Phone sign page blocks the canvas, Clear and Submit buttons after submit and shows "Signature sent. The main browser has been notified…"
  * Admin and Licenses sign panels now display "Signature received from phone and synchronized here."
* **licenses,rental: Guard SVG→PNG legacy rendering against size-less SVG**
  * `_render_svg_to_png_data_url` no longer 500s when `cairosvg.svg2png` cannot render an SVG without intrinsic dimensions; it falls back to `None` like the other failure paths
* **licenses: Preserve original confirmed_at/confirmed_by across unconfirm/reconfirm**
  * `LicenseAdmin` bulk actions and `save_model` now only fill `confirmed_at`/`confirmed_by` on first confirmation and keep the originals on reconfirm; unconfirm no longer wipes the audit fields so events after a reconfirm keep the first confirmation metadata
* **licenses: Remove unused `LicensesConfig` Freistellung fields from admin fieldset**
  * Fieldset now exposes only `freistellung_city`; the other flags are managed via settings/migration and were causing stale display in the admin
* **admin: Switch raw-SVG/HTML admin displays to `mark_safe` / `format_html_join`**
  * Eliminates `format_html` double-escaping for inline SVGs and error-log `<li>` lists across `licenses`, `media_files`, `inventory`, `planung`, `projects`, `registration`, `contributions`
* **admin: Declare explicit `export_form_class = ExportForm` on ExportMixin admins**
  * Avoids import-export deprecation warnings across `contributions`, `inventory`, `licenses`
* **ui: Force `text-decoration: none` on sidebar and rental page-nav links**
  * Resolves stray underlines that appeared on hover/focus in the sidebar and rental page navigation
* **tests: Add QR signature status-consume and rental sign-session coverage**
  * New `rental/tests/test_signature.py` covers create/submit/poll/consume for rental signing sessions
  * `licenses/signature_features_tests.py` gains a `consume_returns_payload_before_delete` case
  * `licenses/licenses_tests.py` gains three LicenseAdmin confirm/unconfirm/reconfirm metadata tests
  * `media_files/tests.py` gains `VideoFileAdminDisplayTests` covering fps/duplicate/versions displays and the changelist

2026-06-24 (Version 4.23.0)
==========================

* **media_files: Fix auto-copy to use primary version for playout, all versions for archive**
  * `copy_videos_for_plan` now selects the PRIMARY version (manual flag -> `is_primary_version()` -> best-source fallback) and copies only it to PLAYOUT
  * All source versions (CUSTOM + ARCHIVE) are copied to ARCHIVE, each skipped only if its filename already exists there
  * `is_manual_primary` flag propagates to the archive copy only (PLAYOUT copies stay non-primary since playout is a temporary playing slot)
  * `check_duplicate_before_copy` now matches by number AND filename, allowing different versions of the same number to coexist in one storage
  * Auto-delete from CUSTOM extended to all CUSTOM versions that were successfully archived
  * Added `media_files/auto_copy_tests.py` with 7 tests covering primary selection, archive-all, playout-primary-only, flag propagation, dup check, and auto-delete

2026-06-21 (Version 4.22.0)
==========================

* **licenses: Freistellung print form with staff signature overlay**
  * Added `License.confirmed_at` (DateTimeField) and `License.confirmed_by` (FK to user) to track when and by whom a license was confirmed
  * `LicenseAdmin` bulk confirm action and `save_model` now populate `confirmed_at`/`confirmed_by`; unconfirm clears them
  * Added `LicensesConfig` Freistellung fields: `freistellung_enabled`, `freistellung_city`, `freistellung_signature_user`, `freistellung_signature_text`, `freistellung_sendezeit_no_protection`, `freistellung_sendezeit_with_protection`, `freistellung_sendezeit_time`
  * `LicensesConfigAdmin` exposes a "Freistellung Print Form" fieldset and uses autocomplete for the signature user (filtered to staff)
  * PDF generator fills Freistellung-specific form fields (`Gruppieren7/8`, `Uhrzeit`, `Ort / Datum`) and overlays the confirming staff member's signature on page 2 when enabled
  * `_svg_signature_to_image` now accepts `data:image/svg+xml;base64,...` URLs in addition to raw SVG

* **registration: Staff signature canvas on user admin**
  * Added `OKUser.staff_signature_svg` (TextField) and `OKUser.staff_signature_points` (JSONField) for per-staff signatures reused on Freistellung PDFs
  * Custom `UserAdminForm` renders signature fields as hidden inputs; new `change_form.html` provides a signature_pad canvas plus QR-sign panel for staff users only
  * `get_fieldsets` hides the Staff signature section for non-staff users; `search_fields` extended to profile first/last name

2026-06-21 (Version 4.21.0)
===========================

* **deps: Upgrade to Django 6.0.6 and refresh Python/Node dependencies**
  * Upgraded Django from 5.2.7 to 6.0.6
  * Upgraded django-stubs and django-stubs-ext to 6.0.5 for Django 6 compatibility
  * Upgraded djangorestframework to 3.17.1, django-filter to 25.2, django-celery-beat to 2.9.0, django-celery-results to 2.6.0
  * Upgraded django-bootstrap-datepicker-plus to 6.0.0 and asgiref to 3.11.1 for Django 6 compatibility
  * Refreshed patch/minor dependencies across the full stack (pytest, celery, crispy-forms, psycopg2, zope, etc.)
  * Restored Django admin link styling by linking `css/admin/custom_admin.css` in `admin/base_site.html` and removing text underlines introduced in Django 6

* **registration: Phone number validation on register and profile forms**
  * Added German phone number regex validation (+49/0049/0 prefix, 8-15 digits) to `UserDataForm` and `ProfileForm`
  * Fixed swapped phone_number / mobile_number fields in `RegisterView` (bug introduced in Django 6 migration)
  * Added comprehensive test coverage for valid and invalid phone/mobile number cases

* **media_files: EBU R128 loudness normalization for broadcast encoding**
  * Applied FFmpeg `loudnorm=I=-23:TP=-1:LRA=11` filter to all audio encodes (standard and HEVC→H.264 transcode paths)
  * Ensures compliance with TV broadcast loudness standard (EBU R128)

* **deployment: Database readiness check in production entrypoint**
  * Added explicit Django DB connection loop (30 retries, 2s interval) before migrations in `entrypoint.production.sh`
  * Added `start_period: 30s` to PostgreSQL healthcheck in both Docker Compose production configs

* **tests: Django 6 and zope.testbrowser 8 compatibility fixes**
  * Updated admin action form controls from `browser.getControl('Go')` to `browser.getControl(name='index')` across all test modules
  * Fixed export form submissions to use `browser.getForm(index=0).submit()` instead of `browser.getControl('Submit').click()`
  * Updated license tests for German locale text assertions and redirect-based auth (Django 6 no longer raises 404 for unauthenticated views)
  * Converted email/password-reset tests from zope.testbrowser to Django test Client for reliability
  * Fixed `ProfileResource` export test to use direct resource export instead of brittle admin UI interaction

* **admin: ProfileResource export field definitions**
  * Defined explicit `fields` list and `export_order` on `ProfileResource` (Django import-export 4.4+ compatibility)

2026-06-10 (Version 4.20.0)
===========================

* **rental, planung, media_files: Async rendering pipeline and anchor placeholder rules**
  * Registered the Celery task wrapper for automatic return reminders so the existing periodic task executes correctly in workers
  * Changed the media file admin action "Video rendern (Standard-Voreinstellungen)" to queue an async Celery render using the standard plain 1080p25 / 9000 kbps preset without overlays, intro, or outro
  * Added a plain FFmpeg encode path for standard renders and kept overlay / intro-outro rendering in the separate dedicated admin action
  * Promoted successfully rendered `_vN` output files to the primary video version automatically; preview renders remain excluded
  * Added `title_contains` / `contains` support for Planung anchor placeholder rules and updated the German admin help text
  * Fixed the production update script JSX build bootstrap so missing or outdated host Node.js falls back to a Dockerized Node.js runner, and repositories without a lockfile use `npm install` instead of failing on `npm ci`

2026-06-10 (Version 4.19.0)
===========================

* **rental: Replace in-browser Babel JSX compilation with esbuild pre-compilation**
  * Switched JSX compilation from @babel/standalone (in-browser) to esbuild (build-time), eliminating the Babel in-browser transformer warning and reducing page load overhead
  * Extracted inline `<script type="text/babel">` render blocks into separate entry-point JSX files under `rental/static/rental/js/entries/`
  * Added `package.json` with esbuild as dev dependency; `npm run build:js` produces minified JS in `rental/static/rental/js/build/`
  * Updated all 5 rental templates to load pre-compiled `.js` instead of `.jsx`
  * Integrated JSX build step into `deployment/scripts/update.sh` — runs `npm ci && npm run build:js` before Docker image build; auto-installs Node.js if absent
  * Fixed `.dockerignore` to allow `rental/static/rental/js/build/` into the Docker image (was blocked by generic `build/` rule)
  * Added `rental/static/rental/js/build/` to `.gitignore` — compiled assets are generated at deploy time, not committed

2026-06-10 (Version 4.18.0)
===========================

* **rental: Support per-room dates and separate Nextcloud events**
  * Enabled per-room date selection in the rental wizard — each room can have different start/end dates within a single reservation
  * Switched room picker UI from RoomCheckPanel to RoomDateTimeForm for individual date customization
  * Refactored Nextcloud Calendar sync to create separate CalDAV events per room rental instead of one shared event
  * Updated event deletion to handle per-room Nextcloud events individually
  * Fixed German translation for "Please set dates and times in step 2 first"

2026-06-06 (Version 4.17.0)
===========================

* **rental: Add return reminders and booking workflow tools**
  * Added configurable automatic return reminder emails for issued rentals
  * Added room calendar week/month views and equipment set management UI
  * Added rental email attachments support and refreshed German translations

2026-06-06 (Version 4.16.0)
===========================

* **planung: Queue anchor rendering after playout copy readiness**
  * Added copy task tracking on daily plans so anchor rendering can wait until videos are available in playout
  * Changed the anchor render endpoint to queue a Celery chain and return task polling metadata
  * Added frontend status polling for copy and render progress in the planning calendar
  * Refreshed German translation catalogs for updated planning and media workflow strings

2026-06-05 (Version 4.15.0)
===========================

* **planung: Add anchor programme preview renderer**
  * Added Planning Configuration fields for anchor render URL, API key, timeout, wait mode, output filename pattern, playout path prefix, and placeholder rules
  * Added `/api/planning/anchor/render/` to render planned days through the external anchor service
  * Creates a preview license named `Programmvorschau vom DD.MM.YYYY` before rendering and uses its license number in the output filename
  * Sends only the first 8 planned items, randomly selects `m`/`w` voice, omits `kontakt`/`musik`, and uses playout videos or configured placeholders
  * Added a calendar modal button for configured anchor rendering and grouped external actions with export controls
  * Added focused service and endpoint tests for payload shape, planned-day validation, license creation, and render requests

2026-06-03 (Version 4.14.0)
===========================

* **contributions: Fix DISA import edge cases**
  * Added header row length validation
  * Added live contribution deduplication by (license, date, live) key
  * Fixed row boundary checks and empty row detection
  * Fixed no-repetition license tracking not updating `existing_contributions_set`

* **planung: Enhance playout import service**
  * Youth protection mapping changed to `0+` / `12` / `16` / `18` for playout
  * Added `placeholders_created` field to `PlayoutScheduleResult`
  * Added `_start_time` and `_duration_sec` helpers with flexible parsing
  * Calendar weeks JS: fixed placeholder count notification

* **Test infrastructure improvements**
  * Browser fixture: `db` → `transactional_db`, lazy wsgi import, login button fallback
  * pytest.ini: added `--noconftest`-compatible top-level config

* **chore: config and import cleanups**
  * Added `DATABASE_CONN_MAX_AGE` env var support in settings
  * Fixed isort grouping in settings.py

2026-05-31 (Version 4.13.0)
===========================

* **planung: Add year, category, age_rating to playout media API**
  * GET /api/v1/media now includes year (license creation year), category (license category name), and age_rating (12+/16+/18+ mapped from youth protection) in each item
  * Youth protection mapping: none→"", from_12→"12+", from_16→"16+", from_18→"18+"

2026-05-29 (Version 4.12.0)
===========================

* **planung: Send broadcast schedule to external playout**
  * Added Playout Schedule URL to Planning Configuration admin settings
  * The planning `Plan!` action now posts the day's broadcast schedule to `/api/schedule/import/oktools`
  * Schedule payload includes day, start times, item kinds (video/placeholder/live), filenames, titles, youth protection, and enriched media metadata
  * Kind determination: `video` (has VideoFile), `placeholder` (Freistellung without video), `live` (is_live=True)
  * Youth protection category mapping: none → none, from_12 → 12+, from_16 → 16+, from_18 → 18+
  * Added DRF-token-protected playout pull endpoints for media metadata, schedules, air reports, and incoming webhook events
  * Added calendar API documentation modal with German translations and token guidance
  * Added schedule import service, view integration, and test coverage

2026-05-28 (Version 4.11.0)
===========================

* **planung: Send planned media metadata to external playout**
  * Added Planning Configuration admin settings for playout import URL, API key, and timeout
  * The planning `Plan!` action now posts allowlisted media metadata by filename to the configured playout import endpoint
  * Added optional periodic missing-metadata checks against `/api/media/import/missing`
  * Added playout import service tests and view coverage for the planning trigger

2026-05-12 (Version 4.10.3)
===========================

* **rental: Replace print form selection page with Bootstrap dropdown**
  * Single "Print slip" button with dropdown menu when multiple template groups exist
  * Dropdown items open print forms in new tabs; no intermediate page

2026-05-12 (Version 4.10.2)
===========================

* **rental: Add print form selection page instead of inline buttons**
  * Single "Print slip" button on rental detail; redirects directly if one template group
  * Renders print_slip_select.html when both MSA and non-MSA items exist
  * Removed per-organization print buttons from rental detail page

2026-05-12 (Version 4.10.1)
===========================

* **rental: Group non-MSA organizations into single print form**
  * Print buttons now grouped by template: MSA separate, all others combined (org_id=0)
  * PrintFormView handles org_id=0 to exclude MSA items and use default template
  * Maximum 2 print buttons per rental regardless of how many organizations

2026-05-12 (Version 4.10.0)
===========================

* **rental: Add organization-agnostic print form system**
  * Replaced hardcoded PrintFormMSAView/PrintFormOKMQView with unified PrintFormView
  * Template selection: MSA → print_form_msa.html, all other orgs → print_form_okmq.html
  * New URL pattern `/print/<org_id>/<rental_id>/` for any organization
  * Smart print_slip redirect to first organization with items in the rental
  * Per-organization print buttons on rental detail page
  * Backward-compatible redirects for old `/print/msa/` and `/print/okmq/` URLs

2026-05-01 (Version 4.9.0)
==========================

* **rental: Optimize user selection for rental process**
  * Added prioritized initial user fetch with active rental count and limit
  * Updated user serialization to use pre-annotated rental counts
  * Unified user search endpoints to reuse serialization logic
  * Added tests for new user selection and serialization behavior

2026-04-30 (Version 4.8.0)
==========================

* **rental: Add rental request signatures and room calendar**
  * Added digital signature support for rental requests (signature fields, signing sessions)
  * Added room calendar view with day/week display and availability status
  * Added email notifications for rental request approval/rejection and return receipts
  * Added rental request admin form with signature capture
  * New models: RentalConfig with employee organizations, RentalRequest signature fields
  * New templates: sign_session, room_calendar_day, email templates for issued/returned
  * Improved rental detail, wizard, and return views with better UX

* **rental: Enhance UI and filtering**
  * Added search, filters and sorting to rental day calendar
  * Improved calendar filter layout with fixed widths
  * Added standalone search styles for calendar filters
  * Updated rental CSS with improved styling

* **planung: Update calendar weeks view**
  * Improved calendar weeks CSS and JavaScript
  * Updated admin calendar template

* **translations: Update German translations**
  * Updated translations across all modules
  * Added new translation strings for rental features

2026-04-01 (Version 4.7.0)
==========================

* **licenses: Fix Nextcloud 32 upload URL and add configurable chunked upload**
  * Fixed WebDAV upload URL format for Nextcloud 32 compatibility:
    * Changed from `/public.php/webdav/` to `/public.php/dav/files/{token}/`
  * Added configurable chunked upload for large files to improve reliability:
    * New environment variable `NEXTCLOUD_CHUNKED_UPLOAD_ENABLED` to enable/disable chunked upload (default: true)
    * New environment variable `NEXTCLOUD_CHUNKED_UPLOAD_THRESHOLD` - file size threshold in MB (default: 100)
    * New environment variable `NEXTCLOUD_CHUNK_SIZE` - chunk size in MB (default: 10)
  * Updated all deployment config templates (okmq, ok-bayern, ok-nrw) with new chunked upload settings
  * Files larger than threshold now use WebDAV chunked upload protocol (MKCOL → PUT chunks → MOVE assembly)
  * Fallback to direct upload if chunked upload fails
  * Added `X-Requested-With: XMLHttpRequest` headers for better Nextcloud compatibility

2026-03-21 (Version 4.6.0)
==========================

* **registration/licenses: Add Bundesland metadata configuration**
  * Added OrganizationConfig Bundesland selection with automatic Bundesland code generation for metadata exports.
  * Extended the license metadata API to always emit `bundesland`, `bundesland_code`, `allowExchange`, and `allowExchangeOtherStates`.

* **austausch: Normalize metadata and filter feed visibility**
  * Normalized both flat legacy and nested canonical metadata payloads for sync, API import, and admin JSON import flows.
  * Persisted exchange visibility metadata on ExchangeItem records and filtered the feed by same-state vs other-state exchange permissions.
  * Added configurable same-state channel exceptions in Austausch settings for Nextcloud channel folders such as OK Magdeburg and OK Dessau.

2026-03-19 (Version 4.5.0)
==========================

* **rental: Add configurable working hours and pick lists**
  * Added weekday opening-hour fields to rental configuration plus validation helpers for admin and public booking flows.
  * Updated rental dashboards and detail views with working-hour-aware time selection, clearer availability feedback, and printable pick-list support.
  * Added rental migrations, new working-hours tests, and per-item pick-list fields for issue preparation.

* **contributions/dashboard: Extend published metadata output**
  * Added `mediathek_url` to the program schedule API response and admin documentation examples.
  * Improved dashboard chart translation handling and empty-state copy.
  * Kept filtered planning calendar cells out of keyboard navigation while preserving layout.

2026-03-13 (Version 4.4.0)
==========================

* **austausch: Add resumable chunked upload with state tracking**
  * Implemented resumable chunked upload v2 with state file tracking for Nextcloud exchanges
  * Added PROPFIND to check already uploaded chunks on server
  * Added exponential backoff retry logic per chunk
  * Added upload state persistence to /tmp/oktools-uploads/
  * Files >50MB now use resumable chunked upload, smaller files use simple PUT
  * Fixed potential upload interruptions by saving progress state
  * Cleaned up state files and temporary upload directories on completion

2026-03-13 (Version 4.3.4)
==========================

* **austausch: Fix large file export to Nextcloud with chunked upload v2**
  * Implemented proper Nextcloud chunked upload v2 API for files >50MB.
  * Uses MKCOL to create upload directory, PUT chunks with numeric names, MOVE to assemble.
  * Fixes "Expected filesize 0 bytes" errors when uploading large video files (9GB+).
  * Added proper OC-Total-Length headers for quota checks on each chunk.
  * Uses requests.Session for connection reuse during chunked uploads.

2026-03-10 (Version 4.3.3)
==========================

* **licenses/austausch: Mediathek URL backfill and export UX improvements**
  * Added management command `backfill_mediathek_urls` to populate missing Mediathek links for existing licenses.
  * Added Mediathek-oriented admin rescan template and license admin improvements for refresh workflows.
  * Extended exchange export templates/services/tasks with improved result presentation and processing.
  * Added migration `licenses/0024_license_mediathek_url_fields.py` and related test coverage.
  * Added deployment documentation for Mediathek links.

2026-03-10 (Version 4.3.2)
==========================

* **licenses: Mediathek publication notification email**
  * Added a new `mediathek_published` notification event and email templates (subject, text, HTML).
  * Sends a user email with direct Mediathek link when `mediathek_url` is set for the first time.
  * Delivery is deduplicated via notification events to prevent duplicate sends.
  * Admin-triggered Mediathek refresh/rescan flows explicitly disable email sending.
  * Extended email render command support for `mediathek_published` preview.

2026-03-09 (Version 4.3.1)
==========================

* **licenses: Signature session cleanup command**
  * Added management command `cleanup_signing_sessions` to remove expired signature sessions.
  * Added test coverage for signature session cleanup.

* **tools: Video rendering and slideshow improvements**
  * Added duration mode to slideshow creator for fixed-duration or fit-content modes.
  * Improved video generator service with enhanced rendering options.
  * Updated templates for slideshow creator, detail view, and video render job list.
  * Added German translations for tools module.

* **registration: Legal texts and privacy policy**
  * Added legal_texts.py with GDPR and imprint content.
  * Updated privacy policy templates with improved content.
  * Added registration tests for legal text handling.

* **media_files: Video render API tests**
  * Added test coverage for video render API endpoints.

* **General: Settings and URL updates**
  * Added new settings for signature and video features.
  * Updated URL configurations.

2026-03-06 (Version 4.3.0)
==========================

* **licenses: Signature v2 and phone QR signing flow**
  * Added signature v2 fields (SVG, biometric points, metadata, method, signed timestamp) and QR signing sessions with mobile signing page and session lifecycle endpoints.
  * Updated create/update UX to use explicit signature method selection, desktop-first QR recommendation, and phone-to-canvas synchronization before submit.
  * Improved PDF signature insertion by preferring SVG/points rendering and preserving austausch compatibility via `has_any_signature()` checks.
  * Added migration and test coverage for signature session flow and payload validation.

2026-03-05 (Version 4.2.0)
==========================

* **licenses/austausch: Expand metadata API fields and import mapping**
  * Kept `name` for backward compatibility and added metadata fields (`subtitle`, `furtherPersons`, `profile`, `duration`, exchange/repetition/youth flags).
  * Extended Austausch remote metadata mapping to import subtitle, participants, tags, category, profile, and permission flags into local licenses.
  * Added test coverage for extended metadata payload and end-to-end API-based field mapping in Austausch imports.

2026-03-05 (Version 4.1.0)
==========================

* **Austausch: API-backed license identity mapping per channel**
  * Added channel-level OK-Tools API credentials and health tracking in Exchange configuration.
  * Resolved imports by stable `(source_channel, contribution_id)` mapping to prevent title-based license reuse.
  * Embedded channel API settings into `ExchangeConfig` admin and added German translations for new fields.

2026-03-02 (Version 4.0.19)
==========================

* **admin: Replace emoji icons with Feather Icons (Outline) SVGs**
  * Replaced all emoji characters (🎬⚠️✅❌🕒📝🗨️▶️🔍⏳📦📡📁📥💾🔢⏱️📊🎛️📋🔐📤📖🔄✓✗☁️📍) with professional inline Feather Icons SVGs across 22 files in 8 apps.
  * Affected: `planung`, `licenses`, `media_files`, `inventory`, `contributions`, `austausch`, `tools`, `ok_tools`.
  * Added CSS styles for SVG icon sizing and layout in `planung/static/planung/css/calendar_weeks.css`.
  * Changed `calendar_weeks.js` comment detection from emoji text matching to `data-has-comment` attribute.
  * Console/management commands and `.po` translation files are unchanged.

2026-03-02 (Version 4.0.18)
==========================

* **austausch: Fix sync ignoring videos with old modification dates**
  * Updated Nextcloud sync logic to group files first and check `lookback_date` against the latest modification date in the file group.
  * Ensures that older video files (e.g. from 2024) are imported if their associated `.meta.json` was recently generated.

2026-03-02 (Version 4.0.17)
==========================

* **austausch: Fix duration extraction from Nextcloud meta.json**
  * Added duration parsing from .meta.json files when syncing Nextcloud exchange folders.
  * Ensures that durations are correctly populated for ExchangeItems in the database.

2026-02-23 (Version 4.0.16)
==========================

* **media_files: VFR detection and source FPS helpers for FFmpeg pipeline**
  * Added `_source_fps()` helper to extract source video framerate via metadata.
  * Added `_source_is_vfr()` to detect variable frame rate streams using ffprobe r_frame_rate vs avg_frame_rate comparison.
  * Updated rendering tests to match revised preset API (`segment_duration`, `intro_overlays`, `outro_overlays`).

* **chore: gitignore .claude/ and AGENTS.md**
  * Excluded AI tooling directories and knowledge base files from version control.

2026-02-18 (Version 4.0.15)
==========================

* **Rental: dashboard date/time defaults and period handling**
  * Improved date input synchronization in rental dashboard JavaScript.
  * Added automatic default times for period selection and safer end-date correction logic.
  * Updated hint fields to date-only UX while preserving datetime values for backend submission.

* **Rental: admin approval emails now include direct staff view link**
  * Added "View" URL to both HTML and plain-text approval email templates.
  * Extended email context generation and updated German translations.
  * Added test coverage to verify staff detail link in outbound admin emails.

* **Austausch: robust status consistency after successful import retry**
  * Ensured `ExchangeItem` status fields are corrected to imported state after successful completion.
  * Prevented stale failed-state metadata from previous retries.

2026-02-12 (Version 4.0.14)
==========================

* **Bug Fix: Dashboard 500 Error - NoneType in Template Filter**
  * Fixed `TypeError: 'NoneType' object is not subscriptable` in dashboard template rendering
    * Error occurred when `user_display_name` was `None` and filter `first` was applied
    * Added `default` filter protection in `base.html` template (lines 139, 141, 143)
    * Fixed `views.py` to ensure `user_display_name` is never `None` (dashboard view and RentalDashboardView)
    * Fallback chain: username → email → "User" for guaranteed string value
  * **Files modified:**
    * `ok_tools/templates/base.html` - Added `|default:""` filter before `|first|upper`
    * `ok_tools/views.py` - Added fallback to "User" when username/email are None

2026-02-11 (Version 4.0.13)
==========================

* **Internationalization (i18n) improvements**
  * **Program Schedule API i18n**: Added localization support for API responses
    * Info block title now translatable via `_('Info block')`
    * Credits text translatable: `_('A contribution by {}').format(profile)`
    * Dynamic endpoint URL in API documentation modal
  * **API Documentation Modal i18n**: Full translation support for JavaScript UI
    * All modal strings extracted to `contributionsI18n` object
    * Uses Django template `{% trans %}` tags for translation
    * Copy button messages, labels, and descriptions translatable
  * **Middleware language detection improvement**: Enhanced `ForceDefaultLanguageMiddleware`
    * Now respects Django standard language detection (URL/cookie/Accept-Language)
    * Falls back to `LANGUAGE_CODE` only when no language detected
    * Better multi-language support for users with different browser settings
  * **New test**: Added `test_program_api_i18n.py` for i18n API testing
  * **Updated translations**: Refreshed German translations across all modules
    * ok_tools, austausch, licenses, media_files, planung, rental, tools

2026-02-10 (Version 4.0.12)
==========================

* **Contributions: Program Schedule API**
  * **New API endpoint**: Added `/contributions/api/program/` for retrieving program schedules via API
    * Token-based authentication required (similar to license metadata API)
    * Supports single date queries (`date` parameter: YYYY-MM-DD)
    * Supports date range queries (`date_from` and `date_to` parameters)
    * Optional time filtering (`start_time` and `end_time` parameters)
    * Returns formatted program data with automatic info block generation for gaps
  * **Admin integration**: Added API documentation modal in Contributions admin
    * API Documentation button in admin change list
    * Query parameters table with examples
    * cURL and JavaScript code examples
    * Copy-to-clipboard functionality for tokens and examples
    * German translations for all API documentation strings
  * **Smart info blocks**: Automatic generation and merging of info blocks
    * Info blocks automatically inserted for gaps > 1 minute between programs
    * Consecutive info blocks are merged to optimize program schedule
    * Configurable tolerance for gap detection
  * **German translations**: Added complete German translations for API documentation
    * Translations added to `ok_tools/locale/de/LC_MESSAGES/django.po`
    * Covers all UI strings, parameter descriptions, and help texts

2026-02-10 (Version 4.0.11)
==========================

* **Austausch: exported license tracking**
  * **ExportedLicense model**: New model to track exported licenses and prevent duplicate exports
  * **Migration support**: Added migration 0014_exportedlicense.py for ExportedLicense model
  * **Data migration**: Added migration 0015_migrate_exported_licenses.py to migrate existing exported licenses
  * **Export service updates**: Updated export_to_server_service to track exported licenses
  * **Views updates**: Updated views to handle exported license tracking

* **Planning module: calendar weeks UI improvements**
  * **Enhanced calendar weeks admin UI**: Improved layout, interactions, and readability
  * **CSS updates**: Better styling for calendar weeks interface
  * **JavaScript improvements**: Enhanced functionality and user interactions
  * **Template updates**: Improved calendar weeks HTML template

* **Licenses module updates**
  * **License creation template**: Updated create.html with improvements
  * **Views updates**: Enhanced license views functionality

* **Media files tasks updates**
  * **Task improvements**: Updated media_files/tasks.py with enhancements

2026-02-09 (Version 4.0.10)
===========================

* **Tools module enhancements**
  * **Dedicated render queue routing**: Routed all Celery tasks from the Tools module to the `render` queue to isolate heavy workloads
  * **Audio normalization improvements**: Added AI-based denoising with neural networks (arnndn), enhanced analysis, and intelligent recommendations
  * **Loudness normalization**: Added support for dynamic/linear mode detection and compressor linking options
  * **RNN model integration**: Automatic download and integration of RNN models for AI-based audio processing
  * **Analysis improvements**: Enhanced noise analysis with silence detection and audio characteristic analysis

* **Calendar and rental system fixes**
  * **Nextcloud calendar integration**: Fixed multiple room booking issue where separate calendar entries were created for same rental request
  * **Single event creation**: Multiple rooms booked in same time period now create single calendar event with all rooms listed
  * **Event management**: Improved handling of shared events when rooms are added/removed from rental requests

* **Translation and internationalization**
  * **Celery translation compilation**: Added translation compilation in Celery worker startup to ensure consistent language in email notifications
  * **Email localization**: Fixed issue where license notification emails fell back to English in worker processes
  * **Language consistency**: Ensured email templates render in organization's default language in Celery tasks

* **Media files and video processing**
  * **Video duplication management**: Enhanced duplicate detection and management with quality-based prioritization
  * **Storage optimization**: Improved auto-copy mechanisms and archive protection features
  * **Metadata extraction**: Enhanced video metadata extraction and processing capabilities

* **System stability and performance**
  * **Queue management**: Improved Celery task routing and worker distribution
  * **Error handling**: Enhanced error logging and debugging capabilities
  * **Process isolation**: Better separation of email rendering from web request cycle

2026-02-08 (Version 4.0.9)
==========================

* **Deployment configurations update**
  * Updated docker-compose production files with improved service configurations
  * Enhanced environment variable documentation
  * Updated deployment scripts for better reliability
  * Added new configuration templates
* **Media files module improvements**
  * Updated FFmpeg rendering utilities for video processing
  * Enhanced background task processing for media operations

2026-02-08 (Version 4.0.8)
===========================

* **Planning module (Planung): service-layer refactor and calendar UX update**
  * Introduced dedicated planning services (`plan_service`, `validation_service`, `notification_service`, `auto_copy_service`) and wired them into views/admin flows.
  * Added planning domain models and migration `0002_plantemplate_planchangelog` for reusable templates and schedule change history.
  * Reworked calendar week admin UI (template, CSS, JavaScript) with improved layout, interactions, and readability.
  * Extended planning routes/views and added tests for services and views.
  * Updated German translation catalogs for planning module and dashboard/admin texts.
* **Licenses and shared UI polish**
  * Improved license update template/view behavior and aligned shared dashboard/page/table styling.

2026-02-06 (Version 4.0.7)
===========================

* **Austausch: network share export destination**
  * Added export destination switch: Nextcloud or Network Share.
  * Added network share path settings, optional subfolder, and Windows root mapping for `files.txt` entries.
  * Implemented atomic copy/write helpers and locked append for stable concurrent export writes.
  * Extended export service and admin UI for network share workflow.
  * Added migration `0013_add_export_destination_network_share`.
  * Added tests for network share export helpers.
* **UI and translations**
  * Minor sidebar/theme/welcome template polish.
  * Updated German translation catalogs across modules.

2026-02-05 (Version 4.0.6)
===========================

* **UI refresh and accessibility**
  * Updated dashboard design system (tokens, layouts, components) and theme styling.
  * Added theme manager with toggle and dark theme updates.
  * Improved dashboard, rental, and accessibility JavaScript with i18n-safe strings.
* **Licenses: UX polish**
  * Refined license detail and edit layouts with improved status rendering.
* **Registration: branding and templates**
  * Added organization logo fields with sidebar branding support.
  * Refreshed login, registration, and profile templates.

2026-02-04 (Version 4.0.5)
===========================

* **Licenses: form UX and upload flow**
  * AJAX form submission returns JSON payload for post-create UI handling.
  * Added translated help texts and modal messages for license creation.
  * Extended create form UI and upload progress handling.
* **Tools: media library additions**
  * Add project media/audio to the library from the slideshow editor.
  * New API endpoints for library conversion with UI actions.
* **Austausch: export timezone polish**
  * Export-to-server selection uses local time for broadcast dates.
  * Export result page loads timezone template filters.
* **Database**
  * Add migration to remove UserJourney.license FK.

2026-02-04 (Version 4.0.4)
===========================

* **Tools: slideshow output & storage path handling**
  * Stream generated slideshows with HTTP Range support for reliable playback.
  * Resolve media/audio/output paths using ToolsConfig storage/output paths with safe fallbacks.
  * Cleanup task now deletes media/audio/output files using resolved paths.
* **Austausch: export & WebDAV fixes**
  * Export result timestamps render in local time.
  * Export-to-server selection list uses local time for broadcast dates.
  * Export result page loads with timezone template filters enabled.
  * Expiring upload shares use local date with safer minimum validity.
  * WebDAV URL resolution uses storage-aware base path.
  * License export skips numbers already successfully exported across runs.
* **Licenses: deletion safety**
  * Clear UserJourney links before deleting confirmed licenses.
* **Project hygiene**
  * Ignore local plans/ folder in Git.

2026-01-28 (Version 4.0.3)
===========================

* **Austausch: Export to server**
  * **Export to server workflow**: Upload video, PDF, JSON (and optional thumbnails) to Nextcloud WebDAV
    * Step 1: Choose mode (by contributions or by license numbers)
    * Step 2: Select contributions/licenses and start export
    * Result page: success/failure/skipped counts and details
  * **ExchangeConfig**: New export settings
    * `upload_server_path`: WebDAV path for upload (distinct from download/sync paths)
    * `default_media_authority`: Optional preselected "Offener Kanal" for export
    * `local_pdf_fallback_path`, `local_pdf_fallback_path_2`: Local directories for unsigned license PDFs ({number}_*.pdf)
    * `upload_thumbnail_enabled`, `thumbnail_storage_path`: Optional cover/thumbnail upload
  * **ExportToServerRun**: Model for export run results (read-only in Admin)
  * **Celery task**: `export_to_server_task` runs upload in background; Nextcloud service extended for upload
  * **Contributions/Licenses**: Admin actions and serializers extended for export selection

2026-01-26 (Version 4.0.2)
===========================

* **Audio Normalization: AI-based denoising and enhanced analysis**
  * **Neural Network Denoising (arnndn)**: Added support for AI-based audio denoising using RNN models
    * New AI presets: `tv_ai_speech`, `tv_ai_strong`, `web_ai_speech` for better speech clarity
    * Automatic RNN model download during installation/update from public repositories
    * Models stored in `tools/rnn_models/` directory (std.rnnn, lq.rnnn)
    * Fallback to FFT-based denoising (afftdn) if RNN models unavailable
    * Configurable model path via `ToolsConfig.arnndn_model_path` or `TOOLS_ARNNDN_MODEL_PATH`
  * **Enhanced Audio Filters**: Added support for additional FFmpeg filters
    * `lowpass` filter for high-frequency noise removal (10-14 kHz)
    * `dialoguenhance` filter for speech clarity improvement in stereo (FFmpeg 5+)
    * Improved filter chain building with automatic model detection
  * **Noise Analysis**: Automatic noise detection and analysis
    * Uses `silencedetect` and `astats` filters to analyze audio characteristics
    * Detects background noise level, silence ratio, peak levels
    * Noise analysis data stored in job metadata for recommendations
    * Displayed in UI with detailed metrics (silence ratio, noise level, peak/mean levels)
  * **Intelligent Recommendations**: Enhanced recommendation system based on audio analysis
    * AI presets recommended when high background noise detected (> -40 dB)
    * Strong AI preset recommended for very high noise (> -35 dB) or continuous noise
    * Recommendations adapt to target (TV vs Web) and model availability
    * Suggestions include specific reasons (noise level, dynamics, peak levels)
  * **Automatic Model Installation**: RNN models downloaded automatically
    * Script `tools/rnn_models/download_models.sh` downloads models during install/update
    * Integrated into `install.sh`, `update.sh`, and `entrypoint.production.sh`
    * Models downloaded from GitHub repositories (GregorR/rnnoise-models)
    * Non-critical: system continues if download fails (manual download possible)
  * **Default Model Path**: Automatic detection of default model location
    * System automatically uses `tools/rnn_models/std.rnnn` if available
    * No manual configuration required if models are in default location
    * Override via config or environment variable if needed

2026-01-23 (Version 4.0.1)
==========================

* **Licenses: status email targeting and user-upload chain**
  * **LicensesConfig**
    * New `notification_media_authority_names`: send status emails only to users whose
      Profile belongs to selected Media Authorities (Offene Kanäle/Bürgermedien).
      Empty = send to all. Configure in Admin → Licenses → Licenses configuration.
  * **NextcloudVideoFile**
    * New `user_uploaded`: True when the rightsholder uploads via the portal; False
      when staff creates the record (e.g. in Admin). Shown in Admin.
  * **Email chain (draft_scheduled, planned_scheduled, contributions_available)**
    * Sent only if the license has a **user-uploaded** Nextcloud video
      (`user_uploaded=True`). Archive-only or staff-linked videos no longer trigger
      these three emails.
  * **video_uploaded** still sent for any new NextcloudVideoFile; all four types
    are filtered by `notification_media_authority_names` when set.

2026-01-20 (Version 4.0.0)
==========================

* **Major Release: Config & Tools Consolidation**
  * **New app: Tools**
    * **Video slideshow creator** (models, views, templates) with async generation via Celery
    * **Video render jobs** (models, views, templates) + rendering pipeline utilities
    * **Preset management UI** in Django admin (preset editor + VideoPreset admin pages)
    * **Audio normalize jobs** (models, services, presets JSON, waveform generation) + Celery tasks
    * **New Tools API endpoints** (project/job CRUD and status endpoints)
  * **DB-backed module configuration (with env fallbacks)**
    * **Registration**: `RegistrationConfig` + `OrganizationConfig` (+ migrations)
    * **Rental**: `RentalConfig` (+ migration) and centralized config helpers
    * **Licenses**: `LicensesConfig` (+ migrations) incl. download path + email toggles
    * **Media Files**: `MediaFilesConfig` (+ migrations) incl. supported formats + HEVC transcode toggle
    * **Tools**: Tools config model added as part of new app
    * **Migration helper command**: `migrate_module_configs` (fills DB config from env for empty/default values)
  * **Licenses: workflow notifications & automation**
    * **License notification event model** + Celery tasks for scheduled status emails
    * **Email templates** added (draft/planned scheduled, video uploaded, contributions available)
    * Updates to serializers/services/views for Nextcloud + notification flow
  * **Media Files refactor**
    * **Video presets moved out of `media_files` into Tools presets infrastructure** (+ migration)
    * Admin/commands/tasks cleanup and maintenance improvements
    * Added admin confirmation template for force-deleting protected archive entries
  * **Dashboard & analytics**
    * Cache invalidation and signal handling updates
    * Widget improvements (inventory/projects/funnel) + dashboard base template update
  * **Deployment & operations**
    * Updated `.env` templates with new module flags/settings (Tools, configs, tasks)
    * Entrypoint/update scripts run config migration step (`migrate_module_configs`)
  * **Translations**
    * Updated German `.po` files across modules and added Tools translations

2026-01-15 (Version 3.3.1)
===========================

* **Tools Module: Media Library**
  * **Media Library**: Reusable media files across multiple projects
    * Upload images and videos to shared library
    * Browse library by media type (images/videos)
    * Add library media to any project without re-uploading
    * Staff-only access to library management
    * Separate API endpoints for library operations
  * **Bug Fixes**
    * Fixed black background for padded media (was green)

2026-01-15 (Version 3.3.0)
===========================

* **New Module: Tools**
  * **Video Slideshow Generator**: Create video slideshows from images and videos
    * Drag & drop interface for media upload
    * Audio background music selection
    * Configurable transitions (fade, wipe, slide, etc.)
    * Adjustable duration and quality settings
    * Preview and download capabilities
    * Async generation via Celery
  * Module can be enabled/disabled via `TOOLS_ENABLED` environment variable
  * Storage paths configurable via `TOOLS_STORAGE_PATH` and `TOOLS_OUTPUT_PATH`
  * Automatic cleanup of old projects via Celery Beat

2026-01-14 (Version 3.2.12)
===========================

* **Rental System Updates**
  * **Email confirmations** now include booking details and HTML versions
  * **User-friendly booking links** via `RENTAL_REQUEST_URL_TEMPLATE`
  * **User detail page** at `/rental/user/rental/<id>/` with request summary
  * **Admin confirmation action** for draft requests in rental detail view
  * **User/Admin request visibility** improvements in dashboards
  * **Deployment templates** updated with `RENTAL_REQUEST_URL_TEMPLATE`

2026-01-12 (Version 3.2.11)
===========================

* **Planning Module (Planung) Enhancements**
  * **Manual Time Setting Improvements**: Enhanced manual time setting with overlap protection
    * Strict mode: Manual time settings are preserved and not auto-adjusted
    * Added overlap validation to prevent videos from overlapping when manually positioned
    * Videos cannot start before the previous video ends (even in manual mode)
    * Visual indicator (light blue background) for manually set times
  * **Multi-Day Video Support**: Added support for videos extending beyond midnight
    * End times now display day offset when video extends to next day (e.g., "02:00:00 (+1 day)")
    * Day offset shown in small gray text below the time (similar to seconds display)
    * Proper handling of videos longer than the broadcast block
    * Correct time calculation across day boundaries
  * **German Translations**: Added German translations for new messages
    * "day" → "Tag"
    * Overlap warning messages in German

2026-01-07 (Version 3.2.10)
===========================

* **Admin Interface Improvements**
  * **SVG Icons Replacement**: Replaced Unicode triangle characters with SVG icons for better rendering
    * Admin sidebar and index page now use SVG triangle icons instead of Unicode characters
    * SVG icons provide consistent rendering across all platforms and browsers
    * No dependency on font support for special Unicode characters
    * Better visual quality with crisp rendering at any size
    * Proper white color (#ffffff) with !important flags to prevent theme overrides
    * Removed all font-family, font-style, and font-weight dependencies
    * Clean SVG implementation with proper path styling
  * **Play Icon SVG**: Replaced Unicode play character with SVG icon in exchange feed
    * Exchange feed video previews now use SVG play icon instead of Unicode character
    * Better visual quality with drop-shadow effect
    * Consistent rendering across all platforms
    * Proper sizing (128x128px) with responsive display

* **Content Exchange Module Enhancements**
  * **Filename Normalization**: Added comprehensive filename normalization for exchange imports
    * German umlaut support: ü->ue, ä->ae, ö->oe, ß->ss
    * Normalize non-ASCII characters using Unicode decomposition
    * Sanitize filenames for filesystem compatibility
    * Remove or replace invalid filesystem characters
    * Remove multiple consecutive underscores
  * **Error Handling Improvements**: Enhanced error handling in ExchangeImport admin
    * Added error message display in ExchangeImport admin list
    * Error messages truncated to 100 characters with full message in tooltip
    * Red color styling for error visibility
  * **Statistics Improvements**: Improved exchange feed statistics
    * Statistics now only count video items (matching queryset filter)
    * Added failed items counter to exchange feed statistics
    * Failed count displayed with red color for visibility
  * **Play Icon Rendering**: Improved play icon rendering in exchange feed template
    * Added !important flag to play icon color for better visibility
    * Added explicit font family stack for Unicode triangle character
    * Included monospace fallback for consistent rendering
    * Added font-style and font-weight normalization
    * Improved cross-platform compatibility

* **Admin Interface Fixes**
  * **Icon Color Fix**: Fixed icon color in admin sidebar and index page
    * Replaced CSS variable with explicit white color (#fff) for better compatibility
    * Ensures icons are always visible regardless of theme settings
    * Applied !important flag to prevent theme overrides

2026-01-07 (Version 3.2.9)
==========================

* **Content Exchange Module Enhancements**
  * **Automatic Thumbnail Generation**: Added automatic thumbnail generation for exchange videos
    * Thumbnails are generated on-demand from video files via HTTP URL (WebDAV)
    * Supports both standard WebDAV and GroupFolders paths
    * Thumbnails are cached locally to avoid repeated generation
    * Fallback mechanism: direct HTTP input, then range download if first method fails
    * Integration with exchange feed view for visual preview
  * **HTTP Thumbnail Generation**: New utility functions for generating thumbnails from HTTP URLs
    * `generate_thumbnail_from_http_url()` - Direct HTTP input with seeking support
    * `generate_thumbnail_from_http_range()` - Range request fallback for compatibility
    * Both methods support HTTP authentication (username:password@host format)
    * Configurable timeout (60 seconds for HTTP URLs vs 10 seconds for local files)
    * Efficient seeking without downloading entire video file
  * **WebDAV URL Resolution**: Improved WebDAV URL handling for different Nextcloud storage types
    * New `get_webdav_url_for_path()` method to determine correct WebDAV base URL
    * Automatic detection of GroupFolders vs standard WebDAV paths
    * Proper URL encoding for special characters in file paths
  * **Template Improvements**: Enhanced exchange feed template for better thumbnail display
    * Improved error handling for missing thumbnails
    * Graceful fallback to play icon if thumbnail generation fails
    * Better visual feedback with onload/onerror handlers

* **Media Files Utils Enhancements**
  * **HTTP URL Support**: Extended `generate_thumbnail()` function to support HTTP/HTTPS URLs
    * Automatically detects HTTP URLs and increases timeout accordingly
    * Works with WebDAV endpoints for remote video file processing
    * Supports both local file paths and HTTP URLs seamlessly

2026-01-07 (Version 3.2.8)
==========================

* **Content Exchange Module (Austausch)**
  * **New Module for Content Exchange**: Added comprehensive content exchange module for sharing content between channels
    * Nextcloud folder synchronization for automatic content discovery
    * Exchange item tracking with video files, PDFs, and thumbnails
    * Contribution ID extraction from filenames for OK-Tools managed content
    * Exchange feed view accessible to staff members via admin interface
    * Configurable sync schedule via Celery Beat (default: daily at 2:00 AM)
    * Support for multiple exchange folders and channel identification
    * Optional module - enabled via `AUSTAUSCH_ENABLED` environment variable
  * **Configuration Templates Updated**: Added Austausch configuration to all deployment templates
    * Added `AUSTAUSCH_ENABLED` setting to ok-bayern, ok-nrw, and okmq templates
    * Added `CELERY_BEAT_SYNC_EXCHANGE` cron schedule configuration
    * Default: disabled for backward compatibility
  * **Admin Integration**: Exchange Feed link added to admin sidebar when module is enabled
    * Accessible via Austausch → Exchange Feed in admin menu
    * Staff-only access with login requirement
    * Paginated list view with filtering and search capabilities
  * **Celery Task Integration**: New periodic task `sync_exchange_folders` for automated synchronization
    * Runs automatically when module is enabled and Celery Beat is configured
    * Integrated with `setup_periodic_tasks` management command
    * Configurable schedule via environment variable

* **Media Files Migration**
  * **Database Schema Update**: Added verbose name to VideoFile.created_at field
    * Migration 0015_alter_videofile_created_at.py
    * Improves admin interface display consistency

2026-01-05 (Version 3.2.7)
==========================

* **Bug Fix: Video Deletion Error**
  * **Fixed UnboundLocalError in VideoFile bulk deletion**: Resolved 500 error when deleting videos through admin interface
    * Removed duplicate local import of translation function `_` that caused scope issue
    * Translation function now correctly uses module-level import throughout the method
    * Bulk deletion of videos now works without Internal Server Error

2026-01-02 (Version 3.2.6)
==========================

* **Celery Integration for System Management Commands**
  * **All System Management Commands Now Run via Celery**: Migrated all management commands to asynchronous execution
    * System Management page commands now execute via Celery tasks instead of blocking web requests
    * Commands include: scan_video_storage, auto_scan, sync_licenses_videos, link_orphan_licenses, cleanup_playout, find_duplicates, cleanup_duplicates
    * Tasks run in background, allowing users to continue working while commands execute
    * Improved scalability - can distribute workload across multiple Celery workers
  * **Storage Location Scanning via Celery**: Scan button and bulk scan actions now use Celery
    * Individual storage scan button (🔍 Scan) now queues Celery task instead of blocking
    * Bulk "Scan selected storage locations" action queues tasks for all selected storages
    * All scan operations execute asynchronously in background
    * Users receive Task ID and link to monitor progress via Celery Results admin
  * **Enhanced User Feedback**: Improved task status tracking and user notifications
    * Task ID displayed after queuing commands
    * Direct links to Celery Results admin page for monitoring task progress
    * Better error handling and user messaging for task queueing
    * All task executions are logged with user information for audit trail

2026-01-02 (Version 3.2.5)
==========================

* **Performance Optimization: Checksum Verification**
  * **Size-Only Verification for ARCHIVE Sources**: Major performance improvement for copying from archive
    * Uses file size comparison instead of checksum calculation for ARCHIVE sources
    * No checksum calculation at all - only compares file sizes before and after copy
    * Verification takes milliseconds instead of minutes (8-9 minutes saved per 6-7 GB file)
    * Archive files are already verified, so size comparison is sufficient for integrity check
    * Significantly reduces copy time: from ~11 minutes to ~2.5-3 minutes for large files
  * **Optimized Checksum Calculation During Copy**: Checksum calculated during file copy, not after
    * Destination checksum is calculated chunk-by-chunk during copy operation
    * Avoids reading file twice (source checksum + copy + destination checksum)
    * Uses 8 MB chunks for better performance
    * Applies to CUSTOM sources (ARCHIVE uses size-only verification)
  * **Configurable Checksum Verification**: Added settings to control checksum verification
    * `VIDEO_COPY_VERIFY_CHECKSUM`: Enable/disable checksum verification (default: true)
    * `VIDEO_COPY_USE_MD5_FOR_ARCHIVE`: Use faster MD5 for ARCHIVE sources (default: true, but ARCHIVE now uses size-only)
    * Allows fine-tuning between security and performance
  * **Improved Logging for Checksum Operations**: Enhanced logging to track verification method
    * Added INFO-level logging to show verification method (size-only vs checksum)
    * Logs file copy progress and verification steps for better debugging
    * Helps monitor performance improvements and verify correct verification method

2026-01-02 (Version 3.2.4)
==========================

* **Bug Fix: Video Deletion from CUSTOM Storage**
  * **Fixed Database Error**: Resolved error when deleting VideoFile records from CUSTOM storage after successful copy
    * Fixed `ValueError: save() prohibited to prevent data loss due to unsaved related object 'video_file'`
    * FileOperation records are now saved before deleting VideoFile to prevent database errors
    * Operation status is updated and saved before VideoFile deletion
    * Improved error handling for cases when source file is missing
    * All database records are now properly updated during deletion operations

2026-01-02 (Version 3.2.3)
==========================

* **Video Storage Automation Enhancements**
  * **Default Playout Storage Selection**: Added intelligent selection of default playout storage for main broadcasts
    * Configurable via `VIDEO_DEFAULT_PLAYOUT_STORAGE_NAME` or `VIDEO_DEFAULT_PLAYOUT_STORAGE_PATH`
    * Auto-detects storage containing "000_Sendungen" in path or "Sendungen" in name
    * Falls back to first available PLAYOUT storage if nothing matches
    * Ensures videos are copied to correct playout location (main broadcasts vs. previews/trailers)
  * **Automatic Deletion from CUSTOM Storage**: Added automatic cleanup of CUSTOM storage after successful copy
    * Videos are moved (deleted from CUSTOM) after successful copy to archive and playout
    * Only deletes if source was CUSTOM and all required copies succeeded
    * Prevents duplicate records and keeps CUSTOM storage (entry point) clean
    * Configurable via `VIDEO_AUTO_DELETE_FROM_CUSTOM` setting (default: true)
    * Creates FileOperation records for deletion tracking
    * Updates all database records properly during copy and delete operations
  * **Enhanced Database Record Management**: Improved database record updates during video operations
    * All metadata is copied when creating new VideoFile records
    * FileOperation records are properly linked to new video records
    * Deletion operations are fully tracked in FileOperation table
    * Better logging for all database operations

2026-01-02 (Version 3.2.2)
==========================

* **Video Storage Automation and Archive Protection**
  * **Automatic Video Copying During Planning**: Added automatic video file copying when saving broadcast plans
    * Videos are automatically copied to archive and playout storage when plan is saved (not draft)
    * Smart source selection: prefers CUSTOM storage if file is recent (within configured days), otherwise uses ARCHIVE
    * Supports weekly folder organization (YYYY_KW_WW format) in playout storage
    * Configurable via environment variables for different installation types
    * Comprehensive logging and error handling
  * **Archive Storage Protection**: Added protection against accidental deletion of archive videos
    * Videos in ARCHIVE storage can be read and copied, but deletion is disabled in admin interface
    * Protection can be enabled/disabled via `VIDEO_ARCHIVE_PROTECTED` setting
    * Works for both single and bulk deletion operations
    * Prevents data loss while allowing read and copy operations
  * **Smart Source Selection**: Intelligent video source selection for copying operations
    * Prefers CUSTOM storage if file was updated within configured days (default: 7 days)
    * Falls back to ARCHIVE storage for older files
    * Excludes PLAYOUT storage from source selection to avoid circular copying
    * Configurable via `VIDEO_SOURCE_PREFERENCE_CUSTOM_DAYS` setting
  * **Configuration via Environment Variables**: Added 6 new settings for flexible configuration
    * `VIDEO_AUTO_COPY_ON_SCHEDULE`: Enable automatic copying when saving plans
    * `VIDEO_AUTO_COPY_TO_ARCHIVE`: Copy videos to archive storage automatically
    * `VIDEO_AUTO_COPY_TO_PLAYOUT`: Copy videos to playout storage automatically
    * `VIDEO_USE_WEEKLY_FOLDERS`: Use weekly folders (YYYY_KW_WW) in playout storage
    * `VIDEO_ARCHIVE_PROTECTED`: Protect archive from deletion (default: true)
    * `VIDEO_SOURCE_PREFERENCE_CUSTOM_DAYS`: Days to consider CUSTOM files as recent (default: 7)
    * All settings default to safe values (disabled) for backward compatibility
  * **Celery Task Integration**: New Celery task `copy_videos_for_plan` for asynchronous video copying
    * Runs automatically when plan is saved (if enabled)
    * Can run synchronously if Celery is not available
    * Returns detailed results for user notifications
    * Handles errors gracefully with comprehensive logging
  * **Documentation Updates**: Added comprehensive documentation for new features
    * New section in ENV_VARIABLES.md for video storage automation configuration
    * Examples for different installation types (with/without archive)
    * Configuration examples for full automation vs. disabled mode

2026-01-02 (Version 3.2.1)
==========================

* **Celery Configuration Improvements**
  * **Configurable Task Time Limits**: Added support for configuring Celery task time limits via environment variables
    * `CELERY_TASK_TIME_LIMIT` and `CELERY_TASK_SOFT_TIME_LIMIT` can now be set in `.env` files
    * Default values remain 30 minutes (hard limit) and 25 minutes (soft limit)
    * Recommended values for large video rendering: 60-120 minutes
    * Updated all configuration templates (okmq, ok-nrw, ok-bayern) with recommended values
  * **Video Rendering**: Fixed timeout issues for long video rendering tasks by making time limits configurable

2026-01-02 (Version 3.2)
========================

* **Documentation Enhancements**
  * **Comprehensive README Update**: Significantly expanded README.rst with detailed module descriptions
    * Added detailed feature descriptions for all core applications (User Registration, License Management, Media Files, Planning Tools, Contributions, Projects, Inventory, Rental, Dashboard)
    * Documented all management commands organized by module (Media Files, Rental, Inventory, Licenses, Contributions, Registration, Dashboard)
    * Added comprehensive data import documentation (DISA, Inventory, Inspections) with format support and batch processing details
    * Documented service layer architecture (Inventory, Rental, Statistics, Notification, User services)
    * Added technical details about caching strategies, database optimization, and API performance
    * Enhanced feature descriptions with sub-features and capabilities for each module
  * **Module Documentation**: Complete feature breakdown for each application
    * User Registration: Email-based authentication, GDPR compliance, profile management, print registration forms
    * License Management: Nextcloud integration, video upload, metadata export, planning system integration
    * Media Files: Multiple storage locations, video rendering with presets, checksum calculation, automatic scanning
    * Planning Tools: Daily broadcast plans (TagesPlan), calendar weeks, time extraction, JSON-based storage
    * Contributions: DISA import (XLSX/XLS), primary/repetition detection, statistics, grouped display
    * Projects: ICS export, categories, target groups, demographics, project leaders
    * Inventory: Hierarchical locations, batch imports (500 items), inspection import, audit logging
    * Rental: Equipment sets, room rentals, transactions, API endpoints, availability checking
    * Dashboard: Multiple widgets, funnel metrics, alert system, real-time updates

* **Management Commands Documentation**
  * Documented all available management commands organized by module:
    * **Media Files**: auto_scan, scan_video_storage, update_video_metadata, link_orphan_licenses, sync_licenses_videos, copy_to_playout, cleanup_playout, cleanup_missing_files, cleanup_old_file_operations, find_duplicates, cleanup_duplicates
    * **Rental**: expire_room_rentals, fix_quantity_issued, fix_missing_issue_transactions, test_nextcloud_calendar
    * **Inventory**: import_inspections, link_inspections, import_locations
    * **Licenses**: import_licenses_from_wp, delete_imported_licenses, cleanup_deleted_nextcloud_videos
    * **Contributions**: export_mediathek_report
    * **Registration**: setup_organizations
    * **Dashboard**: check_alerts
  * Noted that many commands can be run from admin interface via System Management page (requires staff access)

* **Data Import Documentation**
  * **DISA Import**: Documented Excel import (XLSX/XLS) with automatic format conversion, date-based filtering, batch processing, AJAX date extraction, and validation
  * **Inventory Import**: Documented Excel import with batch processing (500 items per batch), automatic entity creation (manufacturers, categories, locations, organizations), inventory number validation (OK-XXXX format), location hierarchy creation, error logging, and status tracking
  * **Inspection Import**: Documented CSV/XLSX import with automatic date parsing from various formats, linking to inventory items by inspection number, batch processing, and error handling

* **Technical Architecture Documentation**
  * **Service Layer**: Documented service layer architecture with Inventory, Rental, Statistics, Notification, and User services for better testability and maintainability
  * **Caching Strategy**: Documented Redis-based caching with pattern-based cache key management, cache invalidation on data changes via signals, and cache versioning support
  * **Database Optimization**: Documented batch processing for imports, optimized contribution primary/repetition detection, query optimization with select_related and prefetch_related, composite indexes, and pagination with preserved prefetch relationships
  * **API Documentation**: Enhanced REST API documentation with pagination support (default 20 items, configurable up to 200), search and filtering capabilities, and ordering support

* **Additional Features Documentation**
  * **Video Rendering**: Documented preset management (database and JSON-based), customizable intro/outro overlays, text and image overlay support, animation effects (fade, slide, zoom), position presets, template-based rendering, and preview functionality
  * **Storage Management**: Documented multiple storage location support with hierarchical tracking, UNC path support for Windows networks, automatic file scanning with scheduling, storage type classification (Archive, Playout, Custom), and file availability tracking
  * **Equipment Sets**: Documented equipment set templates, quick rental setup with equipment sets, member-created equipment sets, and template-based equipment selection
  * **Alert System**: Documented configurable alert thresholds, multiple metric types (conversion rate, absolute count, trend change), alert logging and resolution tracking, notification recipients configuration, and active/inactive threshold management

2026-01-02 (Version 3.2.0)
===========================

* **Bug Fixes and Data Integrity**
  * **Rental Quantity Fix**: Fixed critical double increment bug in `quantity_issued` calculation
    * Resolved issue where `quantity_issued` was incremented twice (once in `create_transaction()` method and once in signal handler)
    * Added management commands `fix_quantity_issued` and `fix_missing_issue_transactions` for data correction
    * Commands support dry-run mode for safe testing before applying fixes
    * Full documentation added in `deployment/docs/FIX_QUANTITY_ISSUED.md`
  * **Transaction Integrity**: Ensured all rental transactions are properly tracked and synchronized
  * **Data Migration Tools**: Added tools to fix existing data affected by the bug

* **License Management Enhancements**
  * **License Cleanup Tools**: Added management command `delete_imported_licenses` for bulk deletion of imported licenses
    * Supports deletion by date range, license number range, or profile ID
    * Includes dry-run mode for safe testing
    * Automatically handles related contributions deletion
  * **Nextcloud Integration**: Added `cleanup_deleted_nextcloud_videos` command for managing deleted videos
    * Checks Nextcloud for deleted videos and marks them as deleted in database
    * Supports configurable grace period before permanent deletion
    * Integrated as periodic Celery task for automated cleanup

* **Periodic Tasks Management**
  * **Task Setup Command**: Added `setup_periodic_tasks` management command for initializing Celery Beat tasks
    * Migrates tasks from `CELERY_BEAT_SCHEDULE` to django-celery-beat database scheduler
    * Makes tasks visible and manageable via Django admin interface
    * Supports update mode for modifying existing tasks
  * **New Periodic Tasks**: Added automated cleanup tasks
    * `cleanup_deleted_nextcloud_videos`: Periodic cleanup of deleted Nextcloud videos
    * All tasks configurable via environment variables with sensible defaults

* **Database Backup Improvements**
  * **Backup Command**: Enhanced `backup_db` management command
    * Supports compression (gzip) for space-efficient backups
    * Configurable output directory
    * Automatic backup rotation via `cleanup_old_backups` task
    * Integrated as periodic Celery task (runs daily by default)

* **Version Updates**
  * **Django**: Updated to 5.2.7 (from 5.2.5)

2025-10-25 (Version 3)
========================

* **Major Architecture Improvements**
  * **Event-Driven Architecture**: Implemented asynchronous communication between rental and inventory modules using Celery events
  * **Service Layer Pattern**: Introduced service layers for inventory and rental operations with abstract interfaces for better decoupling
  * **Microservices Preparation**: Created abstract inventory service interface to prepare for future microservices transition
  **Comprehensive Architecture Documentation**: Added complete C4 model diagrams and architectural overview in `overview.md`

* **Asynchronous Task Processing**
  * **Celery Integration**: Integrated Celery with Redis for background task processing
  * **Async Inventory Import**: Implemented asynchronous inventory import with progress tracking and error handling
  * **Background Processing**: Added Celery workers for long-running operations like imports and exports

* **API Enhancements**
  * **OpenAPI/Swagger Documentation**: Added automatic API documentation with drf-spectacular
  * **REST API for Inventory**: Implemented comprehensive REST API endpoints for inventory management
  * **Token Authentication**: Enhanced API security with token-based authentication and management interface
  * **API Rate Limiting**: Added throttling protection with 100/hour for anonymous and 1000/hour for authenticated users

* **Monitoring and Observability**
  * **Prometheus Integration**: Added comprehensive metrics collection with django-prometheus
  * **JSON Logging**: Implemented structured JSON logging for improved debugging and monitoring
  * **System Metrics**: Added metrics for HTTP requests, database operations, and model operations
  * **Performance Monitoring**: Enhanced dashboard with real-time system statistics

* **Security Enhancements**
  * **Security Headers**: Implemented comprehensive security headers (HSTS, XSS protection, etc.)
  * **CSRF Protection**: Enhanced CSRF protection with secure cookie settings
  * **Clickjacking Protection**: Added X-Frame-Options headers to prevent clickjacking attacks
 * **Vulnerability Scanning**: Integrated pip-audit for automatic dependency vulnerability scanning

* **Code Quality and Type Safety**
  * **Static Type Checking**: Added comprehensive type hints with mypy integration
  * **Code Documentation**: Added Google-style docstrings for all public APIs
  * **Unit Test Coverage**: Added 100+ unit tests for service layers with 70%+ coverage
  * **Code Quality Tools**: Integrated pre-commit hooks and automated code quality checks

* **Performance Optimizations**
  * **Bulk Import Optimization**: Optimized inventory import with bulk_create/bulk_update operations (80% faster)
  * **DISA Import Efficiency**: Improved DISA import performance with reduced database queries (~95% faster)
  * **Database Query Optimization**: Continued optimization of N+1 queries across the application
  * **Cache Improvements**: Enhanced caching strategies for better performance

* **Infrastructure Improvements**
  * **Backup Management**: Added custom management command for PostgreSQL database backups
 * **Configuration Management**: Enhanced .cfg file support for comprehensive Django configuration
  * **Deployment Scripts**: Fixed and improved deployment scripts for production environments
  * **CI/CD Integration**: Enhanced CI pipeline with code coverage and vulnerability scanning

* **Bug Fixes and Stability**
  * **Admin Interface Fixes**: Resolved CSS and display issues in Django admin interface
  * **Error Handling**: Fixed KeyError and AttributeError issues in various components
  * **Import Error Resolution**: Fixed inventory and contribution import error handling
 * **Video Player Fix**: Resolved translation-related errors in video file player

2025-10-11 (Version 2.5)
========================

* **Media Files Management Module**
  * New comprehensive module for video file management
  * Automatic file discovery and metadata extraction via ffprobe
  * Support for multiple storage locations (Archive, Playout, Custom)
  * **Auto-sync duration**: License duration automatically syncs from linked video file
    * Visual warning when durations mismatch
    * One-click sync button in admin interface
    * Automatic sync via signals when video is created/updated
  * **Video player improvements**: Fixed streaming and playback issues
    * Correct MIME-type mapping for all video formats
    * Proper range request support for seeking
    * FileResponse for efficient streaming
    * Inline content disposition (no download prompts)
 * **Duration and Tags formatting**: Improved display in admin interface
    * License duration rounded to seconds (hh:mm:ss format)
    * Tags displayed without JSON brackets and quotes
    * Empty tags show as dash (-) instead of [] or null
  * **Duration mismatch tolerance**: Smart duration comparison
    * Warning only shown if difference >= 1 second
    * Prevents false alerts for sub-second differences (e.g., 0.568s)
    * Auto-sync respects same tolerance threshold
 * **Duplicate Video Management**: Comprehensive duplicate detection and management
    * **Automatic detection**: Finds videos with same number in different storage locations
    * **Quality-based prioritization**: ARCHIVE > PLAYOUT > CUSTOM, then by bitrate/resolution
    * **Checksum verification**: Identifies identical vs different files with same number
    * **Prevention system**: Blocks copying identical files to archive storage
    * **Admin interface enhancements**:
      * Visual duplicate indicators in list view (✓ PRIMARY, ⚠️ DUPLICATE)
      * Filter by duplicate status and version type
      * Bulk actions: mark as primary, delete duplicates
      * Detailed duplicate information in change forms
      * Links between all versions of same video
      * **Management command**: `find_duplicates` with JSON output and filtering options
      * **Auto-copy improvements**: Automatically selects best quality version when copying
      * **Configuration**: New settings for storage priority and duplicate prevention
      * **Documentation**: Complete guides (DUPLICATE_MANAGEMENT.md, DUPLICATE_QUICKSTART.md)
    * **Weekly Folder Organization**: Automatic weekly folder structure for playout storage
      * **Auto-detection**: Automatically determines week from planning date (ISO 8601)
      * **Folder format**: Creates folders like `2025_KW_41` for week 41 of 2025
      * **Auto-copy integration**: Videos copied to correct weekly folder when planning saved
      * **Manual copy support**: Admin copy actions also use weekly folders
      * **Automatic creation**: Creates weekly folders if they don't exist
      * **Database integration**: VideoFile.file_path includes weekly folder path
      * **Backward compatibility**: Existing videos without weekly folders still work
      * **Documentation**: Complete guide (WEEKLY_FOLDERS.md)
    * **Advanced Automation Features**: Comprehensive automation for video file management
      * **Bidirectional sync**: Automatic linking between VideoFile and License (both directions)
      * **Mass synchronization**: `sync_licenses_videos` command for bulk linking and duration sync
      * **Automatic playout cleanup**: Move videos from playout to archive when no longer in use
      * **File attribute monitoring**: Detect when files are in use via system attributes (Windows/Linux)
      * **File lock detection**: Check if files are locked by other processes using `lsof`
      * **Auto-scan integration**: `auto_scan` command for automated storage scanning
      * **Admin actions**: "Move to archive storage" bulk action with safety checks
      * **Cron integration**: Ready for automated daily/weekly maintenance tasks
      * **Comprehensive logging**: All operations tracked in FileOperation model
      * **Admin UI improvements**:
        * **Scan button**: One-click storage scanning from admin interface
        * **Search for videos**: Button to find videos for licenses without files
        * **Bulk search**: Admin action to search videos for multiple licenses
        * **Orphan license finder**: `link_orphan_licenses` command to auto-link videos
        * **System Management**: Centralized page to run all commands from admin UI
          * Auto scan, manual scan, sync licenses, link orphans, cleanup playout, find/cleanup duplicates
          * All commands with configurable options and dry-run support
          * No terminal access required
          * Accessible via MEDIA FILES → 🎛️ System Management in admin sidebar (like planung calendar)
        * **License list enhancements**: Video status column in license admin list
          * Shows video availability status (🎬 Available, ⚠️ Not available, ❌ No video)
          * Play link (▶️ Play) for available videos that opens in popup window (800x600px)
          * Optimized queries with select_related to avoid N+1 problems
        * **Video format detection fix**: Improved MIME-type detection for video playback
          * MIME-type now determined by file extension, not ffprobe format
          * Fixes issue where renamed files (e.g., .mov → .mp4) wouldn't play
          * Videos now stream correctly instead of downloading
          * Updated metadata extraction to prioritize file extension over container format
        * **Video availability fix**: Fixed scan command to properly update video availability
          * Existing videos are now always marked as available when found during scan
          * No longer requires --force or --update-metadata flags for availability updates
          * Missing files are automatically marked as unavailable
          * Scan button in admin now works correctly for updating video status
        * **System Management fixes**: Fixed command parameter mismatches and missing functionality
          * Created missing `cleanup_duplicates` command with proper quality-based duplicate removal
          * Fixed parameter mapping for `find_duplicates` command (removed non-existent options)
          * All management commands now work correctly from System Management page
          * Added dry-run protection for destructive operations
      * **Documentation**: Complete automation guide (ADVANCED_FEATURES.md)
    * **NAS/Network Storage Support**: SMB/CIFS mounting for network shares
      * **Development (Docker/macOS)**:
        * Automatic mount scripts (mount_nas.sh, umount_nas.sh)
        * Docker volume configuration for NAS access
        * Test script for verifying access (test_nas_access.sh)
        * Full documentation: media_files/NAS_SETUP.md
      * **Production (Debian 11/gunicorn)**:
        * Automated setup script (deployment/scripts/setup-nas-debian.sh)
        * Support for multiple NAS with different IP addresses
        * fstab and systemd mount unit configurations
        * Health check and remount scripts
        * Full documentation: deployment/NAS_DEBIAN_SETUP.md
        * Quick start: deployment/PRODUCTION_NAS_QUICKSTART.txt
      * Production configs updated with [media] section (ok-bayern, ok-nrw, okmq)
    * Comprehensive video metadata: codec, bitrate, FPS, resolution, color space, chroma subsampling
    * Audio metadata: codec, bitrate, sample rate, channels, channel layout
    * Built-in video player in Django Admin with HTML5 support and seeking
    * Automatic copy from archive to playout when broadcast plans are saved
    * File integrity verification with SHA256 checksums
    * Complete operation history logging
    * Management commands: scan_video_storage, update_video_metadata, copy_to_playout, cleanup_playout
    * Admin actions: copy to playout, update metadata, verify integrity
    * Integration with License model (one-to-one relationship by number)
    * Integration with Planung module for auto-copying videos
    * Configurable via config file (docker.cfg)
    * Supported formats: mp4, mov, mpeg, mpg (configurable)
    * Full documentation:
      * media_files/README.md - Technical documentation
      * media_files/ADMIN_GUIDE.md - Django Admin user guide with examples
      * media_files/QUICKSTART.md - Quick start guide

2025-10-11 (Version 2.4)
========================

* **Performance Audit and Database Optimization**
  * Comprehensive N+1 query elimination across 13+ files
  * Admin pages optimized: 50-90% reduction in query count
  * Example: RentalRequestAdmin reduced from 301 queries to 3 queries (99% improvement)
  * API endpoints optimized: 30-70% faster loading times
 * Dashboard widgets optimized: 20-50% performance improvement
  
* **Admin Panel Query Optimization**
  * RentalRequestAdmin: Added select_related() for user, created_by, user__profile
  * RentalItemAdmin: Optimized FK queries for inventory_item, manufacturer, location
  * LicenseAdmin: Added prefetch_related() for tags, select_related() for profile/category
  * InventoryItemAdmin: Optimized all FK relationships (manufacturer, category, location, owner)
  * ProfileAdmin: Added select_related() for okuser and media_authority
  * ProjectAdmin: Optimized FK and M2M queries with prefetch_related()
  
* **API Endpoint Optimization**
  * api_get_all_rentals: Fixed paginator prefetch_related() loss issue
  * Implemented post-pagination re-optimization to preserve query efficiency
  * api_get_inventory_schedule: Added inventory_item to select_related()
  * api_users_detail: Added select_related() for okuser and media_authority
  * Reduced API response times by 30-70% under load
  
* **Widget and View Optimization**
  * EquipmentSet loops: Added prefetch_related() for items__inventory_item
  * Dashboard view: Added select_related() for profile.media_authority
  * Reduced widget rendering time by 20-50%
  
* **Documentation and Best Practices**
  * Added performance documentation for problematic methods (get_room_summary, get_inventory_number)
  * Created comprehensive PERFORMANCE_AUDIT_REPORT.md
  * Documented paginator prefetch_related() pitfalls
  * Added recommendations for caching and database indexes
  
* **Dashboard Chart Enhancements**
  * Added total count display in chart titles (e.g., "Age Structure (150)")
  * Added individual value labels in Y-axis for all bars
  * Enhanced data visibility in all dashboard graphs
  * Improved user experience with real-time sum calculations
  
* **Admin Filter UI Improvements**
  * Fixed text color and styling of "Reset" buttons in filters
  * Consistent button styling across datetime and numeric range filters
  * Improved button alignment and readability
  * Enhanced UX with proper CSS variable usage for theme compatibility

2025-10-10 (Version 2.3)
========================

* **API Enhancements**
  * Added token-based authentication API endpoint for license metadata
  * Implemented LicenseMetadataSerializer with comprehensive data export
  * Added `targetChannel` field for PeerTube integration (ActivityPub/Fediverse format)
  * Enhanced `originallyPublishedAt` logic with time extraction from planning system
  * Created comprehensive API tests with authorization and data validation

* **Admin Interface Improvements**
  * Enhanced Token Admin with staff-only user filtering and search functionality
  * Added Django AutocompleteSelect for improved user selection experience
 * Implemented API documentation modal with cURL, JavaScript, and Python examples
  * Added copy-to-clipboard functionality for API tokens and examples
  * Fixed Token registration conflicts and improved error handling
  * Enhanced UserAdmin with extended search fields (email, first_name, last_name)

* **Profile Model Updates**
  * Added `ausweisnummer` field for ID document number storage
  * Implemented data sharing permission checkboxes:
    * `phone_data_sharing_allowed` - permission to share phone number with third parties
    * `email_data_sharing_allowed` - permission to share email address with third parties
  * Organized admin fieldsets with collapsible sections for better UX
 * Excluded admin-only fields from user registration and profile edit forms
  * Enhanced ProfileResource for data export with new fields

* **Custom Widget Development**
  * Created TagsInputWidget for improved tags input in Django Admin
  * Replaced default JSONField with user-friendly interface
  * Added real-time tag preview and validation (maximum 4 tags)
  * Implemented interactive tag removal and automatic comma separation
 * Enhanced form validation with empty tag prevention and duplicate removal
 * Added support for null value handling and clean default display

* **Security and Privacy Enhancements**
  * Implemented GDPR-compliant data sharing permissions
  * Added admin-only access controls for sensitive profile fields
  * Enhanced token authentication with secure API endpoints
  * Improved user data protection with selective field exposure

* **Documentation and Testing**
  * Added comprehensive API documentation with usage examples
  * Created detailed admin interface documentation
  * Implemented extensive test coverage for new features
  * Added migration scripts for database schema updates
 * Enhanced inline code documentation and help texts

* **Database Migrations**
  * Added migration for new Profile model fields
  * Updated License model with tags field and default value changes
 * Implemented data migration for existing records
  * Added database indexes for improved search performance

* **Performance Optimizations**
  * Optimized database queries with select_related() and only() methods
  * Added composite indexes on Profile (first_name, last_name) for faster searches
  * Reduced database queries in API endpoints from 5+ to 1-2 per request
  * Implemented query optimization reducing data transfer by ~70%

* **Security Enhancements**
  * Added API rate limiting (10/hour for anonymous, 1000/hour for authenticated users)
  * Implemented comprehensive API access logging with user and IP tracking
  * Enhanced error handling with detailed logging for debugging
  * Added throttling protection against API abuse and DDoS attacks

* **Admin Interface Improvements**
  * Added fieldsets organization to LicenseAdmin (6 sections with collapsible panels)
  * Improved ProjectAdmin fieldsets with collapsible participant sections and descriptions
 * Added fieldsets to InventoryItemAdmin (5 sections grouped by functionality)
  * Enhanced ContributionAdmin with basic fieldsets for consistency
 * Improved UX with logical grouping: Basic Info → Details → Advanced (collapsed)
  * Reduced admin form scrolling by ~50-70% with smart field organization
  * Added helpful descriptions to complex sections (participant validation, auto-calculated fields)
  * Standardized readonly_fields across all admins for better data integrity

* **User Interface Enhancements**
  * Added Tags (Hashtags) field to user-facing License creation form
 * Integrated TagsInputWidget in License edit form for visual tag management
  * Added tag input with comma-separated values and visual badges
  * Implemented tag validation (max 4 tags) in user interface
 * User-friendly tag management with click-to-remove badges
  * Consistent tag experience between admin and user interfaces

* **Deployment Infrastructure Improvements**
  * Restructured deployment configuration with dedicated `deployment/` directory
  * Added comprehensive Docker deployment support with production-ready configuration
  * Added Gunicorn deployment guide with systemd service files
  * Created ready-to-use configurations for multiple German states (Bayern, NRW, OKMQ)
  * Enhanced configuration files with complete organization settings (description, opening_hours, broadcast times)

* **Documentation Enhancements**
  * Translated all deployment documentation to English
  * Added detailed deployment guides for Docker and Gunicorn methods
  * Created architecture diagrams and deployment comparison tables
  * Updated GitHub repository references throughout the codebase
  * Enhanced configuration file comments with complete state media institution list

* **Configuration Management**
  * Expanded organization configuration with new fields:
    * `description` - Organization description for welcome page
    * `opening_hours` - Formatted opening hours with line breaks
    * `broadcast_start` / `broadcast_end` - Broadcast slot configuration
  * Unified configuration structure across Docker and Gunicorn deployments
  * Added detailed inline documentation for all configuration options

* **Codebase Cleanup**
  * Removed deprecated example configurations from project root
  * Removed outdated systemd service files from scripts/ directory
  * Removed accidentally included odfpy man-pages (share/ directory)
  * Removed legacy development scripts (createsuperuser.py, test_data.py, etc.)
  * Consolidated all deployment-related files under `deployment/` directory
  * Unified requirements files: removed requirements-docker.txt, using single requirements.txt
  * Removed unused reportlab dependency

* **Security and Production Readiness**
  * Enhanced systemd service files with comprehensive security settings
  * Added production-specific environment variable handling
 * Improved SSL/HTTPS configuration examples
 * Added rate limiting and health check configurations for Nginx
  * Enhanced Docker security with user isolation and minimal privileges

2025-09-21
==========

* **Dashboard Analytics System** - Added comprehensive dashboard with interactive charts
  * Multiple chart types: doughnut, bar, horizontal bar with dynamic switching
  * Real-time data visualization for users, projects, licenses, and inventory
 * Export functionality for all chart data
  * Responsive design with adaptive height for large datasets

* **Admin Interface Enhancements**
  * Added direct dashboard link in Django admin menu
 * Hidden specific admin models (Alert Logs, Alert Thresholds, Funnel Metrics, User Journey Stages)
  * Improved admin navigation and user experience

* **Translation System Improvements**
  * Updated German and English translation files (.po/.mo)
  * Added chart-related translations (Doughnut Chart, Bar Chart, Horizontal Bar Chart)
  * Fixed translation compilation issues
  * Added dashboard-specific translation files

* **Chart System Features**
  * Extended color palette (15 colors) to prevent repetition
  * Adaptive container height based on data amount
  * Improved legend display with label truncation
  * Horizontal bar chart support with proper axis configuration
  * Enhanced tooltip functionality

* **Code Quality Improvements**
  * Updated .gitignore to exclude development files
  * Fixed JavaScript translation import issues
  * Improved error handling in dashboard widgets
  * Enhanced responsive design for mobile devices

2023-06-27
==========

* Change the "Nutzeranmeldung" pdf to a more recent version.

* Fix the gender count validation to include all genders which can be selected.

// Training Videos and User Manual (RULES.md TR). Everyone who reads a topic watches its video and
// reads its manual right here on the form. Only System Managers add or change a topic; Frappe shows
// them alone the New button.

(() => {
	// What each file field takes. The server checks the same (training_videos_and_user_manual.py).
	const UPLOADS = { video: [".mp4", ".webm"], manual: [".pdf"] };
	const FILE_URL = /^\/(private\/)?files\//;

	frappe.ui.form.on("Training Videos and User Manual", {
		refresh(frm) {
			for (const [fieldname, allowed] of Object.entries(UPLOADS)) {
				set_upload_options(frm, fieldname, allowed);
			}
			show_video(frm);
			show_manual(frm);
		},
		video(frm) {
			show_video(frm);
		},
		manual(frm) {
			show_manual(frm);
		},
	});

	// A video left playing on a form the user moved away from is paused.
	frappe.router.on("change", () => {
		document.querySelectorAll("video.training-video").forEach((video) => video.pause());
	});

	function set_upload_options(frm, fieldname, allowed) {
		// Only these kinds, always private, and only from this computer.
		const field = frm.get_field(fieldname);
		if (!field) return;
		field.df.options = {
			restrictions: { allowed_file_types: allowed },
			make_attachments_public: false,
			allow_toggle_private: false,
			allow_web_link: false,
			allow_take_photo: false,
			allow_google_drive: false,
			disable_file_browser: true,
		};
	}

	function show_video(frm) {
		show(frm, "video_player", frm.doc.video, (url) =>
			$(`<video class="training-video" controls preload="metadata" playsinline></video>`).attr("src", url)
		);
	}

	function show_manual(frm) {
		show(frm, "manual_viewer", frm.doc.manual, (url) => [
			$(`<iframe class="training-manual"></iframe>`).attr({ src: url, title: __("User Manual") }),
			$(`<div class="training-open"><a target="_blank" rel="noopener"></a></div>`)
				.find("a")
				.attr("href", url)
				.text(__("Open the manual in a new tab"))
				.end(),
		]);
	}

	function show(frm, fieldname, url, make) {
		// Drawn again only when the file changes, so a video keeps playing through a save.
		const field = frm.get_field(fieldname);
		if (!field) return;
		url = FILE_URL.test(url || "") ? url : "";
		if (field.$wrapper.data("training-url") === url) return;
		field.$wrapper.data("training-url", url);
		add_style();
		field.$wrapper.empty();
		if (url) field.$wrapper.append(make(url));
	}

	function add_style() {
		if (document.getElementById("training-style")) return;
		$("head").append(`<style id="training-style">
			.training-video {
				display: block; width: 100%; max-height: 70vh; background: #000;
				border-radius: var(--border-radius-md);
			}
			.training-manual {
				display: block; width: 100%; height: 80vh; border: 1px solid var(--border-color);
				border-radius: var(--border-radius-md); background: var(--subtle-fg);
			}
			.training-open { margin-top: var(--margin-sm, 8px); font-size: var(--text-sm); }
			@media print { .training-video, .training-manual, .training-open { display: none !important; } }
		</style>`);
	}
})();

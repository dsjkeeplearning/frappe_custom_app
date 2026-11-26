// EOMS Docs (RULES.md ED). Everyone reads the document here, page by page, and cannot download it:
// the server draws each page as an image, and a page is fetched only when it scrolls near.
// Only System Managers add or change a record; Frappe shows them alone the New button.

(() => {
	const METHOD = "custom_app.custom_app.doctype.eoms_docs.eoms_docs";
	const ALLOWED = [".pdf", ".doc", ".docx"];
	const AHEAD = "1500px 0px"; // a page starts loading this far before it scrolls into view
	const WIDEST = 900; // CSS pixels a page is shown at, at most

	frappe.ui.form.on("EOMS Docs", {
		onload(frm) {
			if (frm.is_new() && !frm.doc.company) {
				frm.set_value("company", frappe.defaults.get_user_default("Company"));
			}
		},
		refresh(frm) {
			set_upload_options(frm);
			if (!frappe.user.has_role("System Manager")) {
				// The attachment links are closed to readers; there is no need to list them.
				frm.$wrapper.find(".form-attachments").hide();
			}
			show_document(frm);
		},
		upload_doc(frm) {
			show_document(frm);
		},
	});

	function set_upload_options(frm) {
		// Only PDF, DOC or DOCX, always private, and only from this computer.
		const field = frm.get_field("upload_doc");
		if (!field) return;
		field.df.options = {
			restrictions: { allowed_file_types: ALLOWED },
			make_attachments_public: false,
			allow_toggle_private: false,
			allow_web_link: false,
			allow_take_photo: false,
			allow_google_drive: false,
			disable_file_browser: true,
		};
	}

	function show_document(frm) {
		const $wrapper = frm.get_field("viewer").$wrapper;
		if (frm.is_new() || frm.is_dirty()) {
			destroy(frm);
			$wrapper.html(`<div class="eoms-note text-muted">${__("Save to see the document here.")}</div>`);
			return;
		}
		const key = `${frm.doc.name}|${frm.doc.modified}`;
		if (frm.eoms_viewer && frm.eoms_viewer.key === key) return; // keeps the reader's place
		destroy(frm);
		frm.eoms_viewer = new Viewer($wrapper, frm.doc.name, key);
	}

	function destroy(frm) {
		frm.eoms_viewer && frm.eoms_viewer.destroy();
		frm.eoms_viewer = null;
	}

	class Viewer {
		constructor($wrapper, name, key) {
			add_style();
			this.name = name;
			this.key = key;
			this.$root = $(`<div class="eoms-viewer">
				<div class="eoms-count text-muted">${__("Loading the document…")}</div>
				<div class="eoms-pages"></div>
			</div>`);
			$wrapper.empty().append(this.$root);
			protect(this.$root[0]);
			this.load();
		}

		async load() {
			let info;
			try {
				info = await get(`${METHOD}.get_pages`, { name: this.name });
			} catch (e) {
				this.$root.find(".eoms-count").text(__("The document could not be shown."));
				return;
			}
			if (!this.$root) return; // closed meanwhile
			const count = info.pages.length;
			this.$root.find(".eoms-count").text(count === 1 ? __("1 page") : __("{0} pages", [count]));

			const $pages = this.$root.find(".eoms-pages");
			const width = draw_width(info.widths, $pages.width());
			this.observer = "IntersectionObserver" in window
				? new IntersectionObserver((seen) => this.show(seen), { rootMargin: AHEAD })
				: null;

			info.pages.forEach(([w, h], i) => {
				const $page = $(`<div class="eoms-page" style="aspect-ratio: ${w} / ${h}">
					<img alt="" draggable="false">
					<span class="eoms-number">${i + 1} / ${count}</span>
				</div>`);
				const query = new URLSearchParams({ name: this.name, page: i, width, v: info.version });
				$page.find("img").attr("data-src", `/api/method/${METHOD}.get_page?${query}`);
				$pages.append($page);
				this.observer ? this.observer.observe($page[0]) : this.draw($page[0]);
			});
		}

		show(seen) {
			for (const entry of seen) {
				if (!entry.isIntersecting) continue;
				this.observer.unobserve(entry.target);
				this.draw(entry.target);
			}
		}

		draw(page) {
			const img = page.querySelector("img");
			img.onload = () => page.classList.add("loaded");
			img.onerror = () => page.classList.add("failed");
			img.src = img.dataset.src;
		}

		destroy() {
			this.observer && this.observer.disconnect();
			this.$root && this.$root.remove();
			this.$root = null;
		}
	}

	function get(method, args) {
		return new Promise((resolve, reject) => {
			frappe.call({ method, args, type: "GET", callback: (r) => resolve(r.message), error: reject });
		});
	}

	function draw_width(widths, shown) {
		// Sharp on this screen, and no wider: the server rounds up to the next of its widths.
		const wanted = Math.min(shown || WIDEST, WIDEST) * (window.devicePixelRatio || 1);
		return widths.find((w) => w >= wanted) || widths[widths.length - 1];
	}

	function protect(el) {
		// No right-click save, dragging out, selecting or copying. A screenshot cannot be stopped.
		for (const event of ["contextmenu", "dragstart", "selectstart", "copy"]) {
			el.addEventListener(event, (e) => e.preventDefault());
		}
	}

	function add_style() {
		if (document.getElementById("eoms-viewer-style")) return;
		$("head").append(`<style id="eoms-viewer-style">
			.eoms-viewer { user-select: none; -webkit-user-select: none; -webkit-touch-callout: none; }
			.eoms-count { font-size: var(--text-sm); margin-bottom: var(--margin-sm, 8px); }
			.eoms-pages {
				display: flex; flex-direction: column; align-items: center; gap: 16px;
				padding: 16px; background: var(--subtle-fg); border-radius: var(--border-radius-md);
			}
			.eoms-page {
				position: relative; width: 100%; max-width: ${WIDEST}px; background: #fff;
				box-shadow: var(--shadow-sm); border-radius: 2px; overflow: hidden;
			}
			.eoms-page img {
				display: block; width: 100%; height: 100%; opacity: 0; transition: opacity .2s;
				pointer-events: none; -webkit-user-drag: none;
			}
			.eoms-page.loaded img { opacity: 1; }
			.eoms-page:not(.loaded)::before {
				content: ""; position: absolute; inset: 0;
				background: linear-gradient(100deg, #fff 30%, #f3f3f3 50%, #fff 70%);
				background-size: 300% 100%; animation: eoms-wait 1.4s linear infinite;
			}
			.eoms-page.failed::before { animation: none; background: #fff; }
			.eoms-number {
				position: absolute; right: 8px; bottom: 6px; padding: 0 6px; border-radius: 6px;
				font-size: var(--text-xs); color: #6b7280; background: rgba(255, 255, 255, .85);
			}
			.eoms-note { padding: 16px 0; }
			@keyframes eoms-wait { from { background-position: 100% 0; } to { background-position: 0 0; } }
			@media (prefers-reduced-motion: reduce) { .eoms-page:not(.loaded)::before { animation: none; } }
			@media print { .eoms-viewer { display: none !important; } }
		</style>`);
	}
})();

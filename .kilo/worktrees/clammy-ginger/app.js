/* Shared browser logic for the Smart Library System. */
(function () {
  "use strict";

  const API = "/api";
  let currentUser = null;
  let books = [];
  let transactions = [];
  let managedUsers = [];
  let activeBook = null;
  let addingBook = false;
  let coverPreviewUrl = null;

  function escapeHtml(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (character) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[character];
    });
  }

  async function request(path, options) {
    const settings = options || {};
    settings.headers = Object.assign({}, settings.headers || {});
    if (settings.body instanceof FormData) {
      delete settings.headers["Content-Type"];
    } else if (!settings.headers["Content-Type"]) {
      settings.headers["Content-Type"] = "application/json";
    }
    const response = await fetch(API + path, settings);
    const result = await response.json().catch(function () { return {}; });
    if (!response.ok) {
      if (response.status === 401 && window.location.pathname.indexOf(".html") !== -1 &&
          !["/LogIn.html", "/welcome.html", "/EmailVerification.html", "/VerificationCode.html"].includes(window.location.pathname)) {
        window.location.href = "/LogIn.html";
      }
      throw new Error(result.error || "The request could not be completed.");
    }
    return result;
  }

  function notify(message, isError) {
    let notice = document.querySelector(".api-notice");
    if (!notice) {
      const style = document.createElement("style");
      style.textContent = ".api-notice{position:fixed;z-index:200;top:16px;right:16px;max-width:min(420px,calc(100vw - 32px));padding:12px 16px;background:#e2f4e7;color:#174b2e;border:1px solid #39744e;border-radius:6px;box-shadow:0 3px 12px #0002;font:600 14px/1.4 Arial,sans-serif}.api-notice.error{background:#fff0ed;color:#812a20;border-color:#b85649}";
      document.head.appendChild(style);
      notice = document.createElement("div");
      notice.className = "api-notice";
      notice.setAttribute("role", "status");
      document.body.appendChild(notice);
    }
    notice.textContent = message;
    notice.classList.toggle("error", Boolean(isError));
    clearTimeout(notice.timer);
    notice.timer = setTimeout(function () { notice.remove(); }, 4200);
  }

  function addInteractiveStyles() {
    const style = document.createElement("style");
    style.textContent = ".book-actions{display:flex;gap:4px;flex-wrap:wrap}.book-actions button{border:1px solid #224332;background:#e7f1e8;color:#1e3f2e;border-radius:4px;padding:5px 7px;font:600 11px Arial,sans-serif;cursor:pointer}.book-actions button:hover{background:#d5e8d8}.filter-grid .filter-field input{box-sizing:border-box;width:100%;min-width:0;border:0;outline:0;background:transparent;font:600 13px Arial,sans-serif;color:#1e3f2e}.api-dialog{width:min(480px,calc(100vw - 32px));max-height:calc(100vh - 32px);padding:0;border:2px solid #224332;border-radius:6px;color:#1e3f2e;box-shadow:0 12px 36px #0004}.api-dialog::backdrop{background:#10201888}.api-dialog form{padding:22px}.api-dialog h2{margin:0 0 16px;font:700 20px Arial,sans-serif}.api-dialog p{font:14px/1.5 Arial,sans-serif}.api-dialog .dialog-field{display:grid;gap:5px;margin:12px 0}.api-dialog label{font:600 13px Arial,sans-serif}.api-dialog input,.api-dialog select{width:100%;min-height:38px;padding:8px;border:1px solid #809487;border-radius:4px;font:14px Arial,sans-serif}.api-dialog-actions{display:flex;justify-content:flex-end;gap:8px;margin-top:18px}.api-dialog button{min-height:36px;padding:7px 14px;border:1px solid #224332;border-radius:4px;background:#fff;color:#1e3f2e;font:600 13px Arial,sans-serif;cursor:pointer}.api-dialog button[type=submit]{background:#224332;color:#fff}.api-dialog button:hover{filter:brightness(.96)}";
    style.textContent += ".dashboard-card-link{cursor:pointer}.dashboard-card-link:focus-visible{outline:3px solid #39744e;outline-offset:2px}.attendance-dialog{width:min(1100px,calc(100vw - 28px))}.attendance-dialog h2{display:flex;justify-content:space-between;align-items:center}.attendance-dialog h2 button{min-width:34px;padding:2px 8px;font-size:22px}.dialog-table-wrap{max-height:65vh;overflow:auto}.attendance-dialog table{width:100%;min-width:680px;border-collapse:collapse}.attendance-dialog th,.attendance-dialog td{padding:8px 10px;border-bottom:1px solid #d8e2da;text-align:left;font:12px/1.4 Arial,sans-serif}.attendance-dialog th{position:sticky;top:0;background:#224332;color:#fff}.attendance-dialog td{color:#1e3f2e}#log-rows td{white-space:nowrap}";
    document.head.appendChild(style);
    const coverStyle = document.createElement("style");
    coverStyle.textContent = ".cover-controls{display:grid;gap:7px;margin-top:12px}.cover-controls label{display:block;padding:7px 9px;background:#e7f1e8;color:#1e3f2e;border:1px solid #809487;border-radius:4px;font:600 12px Arial,sans-serif;text-align:center;cursor:pointer}.cover-controls input{width:100%;font:11px Arial,sans-serif}.cover-controls>div{display:flex;gap:6px}.cover-controls button{flex:1;padding:6px 8px;border:1px solid #224332;border-radius:4px;background:#e7f1e8;color:#1e3f2e;font:600 11px Arial,sans-serif;cursor:pointer}.cover-controls small{font:11px/1.3 Arial,sans-serif;overflow-wrap:anywhere}#bookCoverImage{max-height:300px;object-fit:contain}";
    document.head.appendChild(coverStyle);
    const managementStyle = document.createElement("style");
    managementStyle.textContent = ".user-view-tabs{display:flex;gap:6px}.user-view-tabs button,.system-role-filter{min-height:34px;padding:7px 10px;border:1px solid #224332;border-radius:4px;background:#fff;color:#1e3f2e;font:600 12px Arial,sans-serif;cursor:pointer}.user-view-tabs button.active{background:#224332;color:#fff}.system-role-filter[hidden]{display:none}.top-action-bar{align-items:center;gap:10px;flex-wrap:wrap}.people-dialog{overflow:auto}.people-dialog form{max-height:calc(100vh - 48px);overflow:auto}.filter-grid .field select,.filter-grid .field input{box-sizing:border-box;width:100%;min-height:34px;padding:6px 8px;border:1px solid #839789;border-radius:4px;background:#fff;color:#1e3f2e;font:13px Arial,sans-serif}";
    document.head.appendChild(managementStyle);
  }

  function clearExampleRows(path) {
    const page = path.split("/").pop();
    if (page === "dashboard.html") {
      document.querySelectorAll(".metrics .num").forEach(function (value) { value.textContent = "--"; });
      const body = document.getElementById("log-rows");
      if (body) body.innerHTML = '<tr><td colspan="5">Loading attendance activity...</td></tr>';
    } else if (page === "book_transactions.html") {
      const body = document.querySelector(".grid-table tbody");
      if (body) body.innerHTML = '<tr><td colspan="9">Loading catalog...</td></tr>';
    } else if (page === "reports.html") {
      const table = document.querySelector(".main table");
      if (table) {
        const filterTitle = document.querySelector(".filter-title");
        const heading = document.querySelector(".stage-header h2, .card-top h2");
        const description = document.querySelector(".stage-header p, .card-top p");
        if (filterTitle) filterTitle.textContent = "Filter Attendance Records";
        if (heading) heading.textContent = "Complete Attendance Records";
        if (description) description.textContent = "Official Time-in and Time-out history recorded by the Smart Library backend.";
        table.querySelector("thead").innerHTML = "<tr><th>SCHOOL ID</th><th>NAME</th><th>ROLE</th><th>DEPARTMENT</th><th>DATE</th><th>TIME-IN</th><th>TIME-OUT</th><th>STATUS</th></tr>";
        table.querySelector("tbody").innerHTML = '<tr><td colspan="8">Loading attendance records...</td></tr>';
      }
    } else if (page === "users_management.html") {
      const body = document.querySelector(".stage tbody");
      if (body) body.innerHTML = '<tr><td colspan="4">Loading users...</td></tr>';
    } else if (page === "time_in_out.html") {
      const body = document.querySelector(".table-container tbody, .stage tbody");
      if (body) body.innerHTML = '<tr><td colspan="8">Loading attendance records...</td></tr>';
    }
  }

  function showDialog(title, fields, message, submitLabel, onSubmit) {
    const dialog = document.createElement("dialog");
    dialog.className = "api-dialog";
    const inputMarkup = fields.map(function (field) {
      let control;
      if (field.type === "select") {
        control = '<select name="' + escapeHtml(field.name) + '"' + (field.required ? " required" : "") + ">" +
          field.options.map(function (option) {
            return '<option value="' + escapeHtml(option.value) + '"' + (option.value === field.value ? " selected" : "") + ">" + escapeHtml(option.label) + "</option>";
          }).join("") + "</select>";
      } else {
        control = '<input name="' + escapeHtml(field.name) + '" type="' + escapeHtml(field.type || "text") +
          '" value="' + escapeHtml(field.value || "") + '"' + (field.required ? " required" : "") +
          (field.placeholder ? ' placeholder="' + escapeHtml(field.placeholder) + '"' : "") + ">";
      }
      return '<div class="dialog-field"><label>' + escapeHtml(field.label) + control + "</label></div>";
    }).join("");
    dialog.innerHTML = '<form method="dialog"><h2>' + escapeHtml(title) + "</h2>" +
      (message ? "<p>" + escapeHtml(message) + "</p>" : "") + inputMarkup +
      '<div class="api-dialog-actions"><button type="button" data-cancel>Cancel</button><button type="submit">' +
      escapeHtml(submitLabel || "Save") + "</button></div></form>";
    document.body.appendChild(dialog);
    dialog.addEventListener("close", function () { dialog.remove(); });
    dialog.querySelector("[data-cancel]").addEventListener("click", function () { dialog.close(); });
    dialog.querySelector("form").addEventListener("submit", function (event) {
      event.preventDefault();
      const values = Object.fromEntries(new FormData(event.currentTarget).entries());
      dialog.close();
      Promise.resolve(onSubmit(values)).catch(function (error) { notify(error.message, true); });
    });
    dialog.showModal();
  }

  function login(event) {
    event.preventDefault();
    const email = document.getElementById("email").value.trim();
    const password = document.getElementById("password").value;
    request("/auth/login", { method: "POST", body: JSON.stringify({ email: email, password: password }) })
      .then(function (result) {
        const destination = result.user.role === "MIS Admin" ? "/MIS_ADMIN/" : "/LIBRARIAN/";
        window.location.href = destination + "dashboard.html";
      })
      .catch(function (error) { notify(error.message, true); });
  }

  function togglePassword(inputId) {
    const input = document.getElementById(inputId || "password");
    if (input) input.type = input.type === "password" ? "text" : "password";
  }

  function bindLogout() {
    document.querySelectorAll(".logout").forEach(function (link) {
      link.addEventListener("click", async function (event) {
        event.preventDefault();
        try {
          await request("/auth/logout", { method: "POST" });
          window.location.href = "/LogIn.html";
        } catch (error) { notify(error.message, true); }
      });
    });
  }

  function updateAccountName() {
    document.querySelectorAll(".who-name").forEach(function (element) {
      element.textContent = currentUser.name;
    });
  }

  function renderDashboard(data) {
    const metricContainer = document.querySelector(".metrics");
    if (metricContainer) {
      const stats = data.stats;
      const cards = [
        ["BORROWED BOOKS", stats.borrowed_books, "borrowed"],
        ["OVERDUE BOOKS", stats.overdue_books, "overdue"],
        ["PEOPLE CURRENTLY INSIDE", stats.people_inside, ""]
      ];
      const template = metricContainer.querySelector(".metric");
      metricContainer.innerHTML = "";
      cards.forEach(function (card) {
        const item = template.cloneNode(true);
        item.classList.remove("dashboard-card-link");
        item.removeAttribute("role");
        item.removeAttribute("tabindex");
        item.removeAttribute("data-dashboard-list");
        if (card[2]) {
          item.classList.add("dashboard-card-link");
          item.setAttribute("role", "button");
          item.tabIndex = 0;
          item.dataset.dashboardList = card[2];
        }
        item.querySelector(".cap").textContent = card[0];
        item.querySelector(".num").textContent = card[1];
        metricContainer.appendChild(item);
      });
    }

    const table = document.querySelector(".logs table");
    const tbody = document.getElementById("log-rows");
    if (table && tbody) {
      const heading = document.querySelector(".logs h2");
      if (heading) heading.textContent = "Live Access Logs";
      table.querySelector("thead").innerHTML = "<tr><th>SCHOOL ID</th><th>NAME</th><th>ROLE</th><th>TIME-IN</th><th>TIME-OUT</th></tr>";
      tbody.innerHTML = data.attendance.length ? data.attendance.map(function (record) {
        return "<tr><td>" + escapeHtml(record.school_id) + "</td><td>" + escapeHtml(record.name) +
          "</td><td>" + escapeHtml(record.role + (record.department ? " / " + record.department : "")) +
          "</td><td>" + escapeHtml(record.time_in) + "</td><td>" + escapeHtml(record.time_out || "--") + "</td></tr>";
      }).join("") : '<tr><td colspan="5">No attendance records yet.</td></tr>';
    }
    bindDashboardCards();
  }

  function showRowsDialog(title, headers, rows) {
    const dialog = document.createElement("dialog");
    dialog.className = "api-dialog attendance-dialog";
    const headerMarkup = headers.map(function (header) { return "<th>" + escapeHtml(header) + "</th>"; }).join("");
    const rowMarkup = rows.length ? rows.map(function (row) {
      return "<tr>" + row.map(function (cell) { return "<td>" + escapeHtml(cell) + "</td>"; }).join("") + "</tr>";
    }).join("") : '<tr><td colspan="' + headers.length + '">No records found.</td></tr>';
    dialog.innerHTML = '<form method="dialog"><h2>' + escapeHtml(title) +
      '<button type="submit" aria-label="Close">&times;</button></h2><div class="dialog-table-wrap"><table><thead><tr>' +
      headerMarkup + "</tr></thead><tbody>" + rowMarkup + '</tbody></table></div></form>';
    document.body.appendChild(dialog);
    dialog.addEventListener("close", function () { dialog.remove(); });
    dialog.showModal();
  }

  function bindDashboardCards() {
    const metricContainer = document.querySelector(".metrics");
    if (!metricContainer || metricContainer.dataset.cardsBound) return;
    metricContainer.dataset.cardsBound = "true";
    const openCard = function (card) {
      const open = async function () {
        const kind = card.dataset.dashboardList;
        const result = await request("/dashboard/" + kind + "-books");
        const records = result.books.map(function (book) {
          const row = [book.school_id, book.borrower_name, book.barcode, book.title, book.borrow_date, book.due_date];
          if (kind === "overdue") row.push(book.days_overdue + " days", book.status);
          else row.push(book.status);
          return row;
        });
        const headers = ["School ID", "Borrower", "Book ID / Barcode", "Book Title", "Borrow Date", "Due Date"];
        headers.push(kind === "overdue" ? "Days Overdue" : "Status");
        if (kind === "overdue") headers.push("Status");
        showRowsDialog(kind === "overdue" ? "Overdue Books" : "Borrowed Books", headers, records);
      };
      open().catch(function (error) { notify(error.message, true); });
    };
    metricContainer.addEventListener("click", function (event) {
      const card = event.target.closest(".dashboard-card-link");
      if (card) openCard(card);
    });
    metricContainer.addEventListener("keydown", function (event) {
      const card = event.target.closest(".dashboard-card-link");
      if (card) {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          openCard(card);
        }
      }
    });
  }

  function bookFields() {
    const result = {};
    const names = {
      "book number": "barcode", "book title": "title", "author name": "author",
      "category": "category", "date published": "published_date", "book count": "quantity", "status": "status"
    };
    document.querySelectorAll("#bookModal .form-group").forEach(function (group) {
      const label = group.querySelector("label");
      const input = group.querySelector("input");
      if (label && input && names[label.textContent.trim().toLowerCase()]) {
        result[names[label.textContent.trim().toLowerCase()]] = input;
      }
    });
    return result;
  }

  function setBookModal(book) {
    const modal = document.getElementById("bookModal");
    if (!modal) return;
    const fields = bookFields();
    activeBook = book;
    addingBook = !book;
    if (coverPreviewUrl) {
      URL.revokeObjectURL(coverPreviewUrl);
      coverPreviewUrl = null;
    }
    const coverImage = document.getElementById("bookCoverImage");
    const coverInput = document.getElementById("bookCoverInput");
    const coverControls = document.getElementById("coverControls");
    const coverFileName = document.getElementById("coverFileName");
    if (coverImage) {
      coverImage.alt = book ? book.title + " cover" : "Book cover image";
      coverImage.src = book && book.cover_image ? "/api/books/" + book.id + "/cover" : "../img/ptc_logo.png";
      coverImage.onerror = function () { coverImage.src = "../img/ptc_logo.png"; };
    }
    if (coverInput) coverInput.value = "";
    if (coverControls) coverControls.hidden = addingBook;
    if (coverFileName) coverFileName.textContent = "Choose an image file";
    Object.keys(fields).forEach(function (key) {
      fields[key].value = book ? (book[key] == null ? "" : book[key]) : "";
      fields[key].readOnly = key === "status" || (!addingBook && key !== "status");
    });
    const activeTransactions = book ? transactions.filter(function (item) {
      return item.book_id === book.id && item.status === "borrowed";
    }) : [];
    const borrower = activeTransactions[0];
    const borrowerValues = [borrower ? borrower.borrower_name : "", borrower ? borrower.borrower_school_id : "",
      borrower ? borrower.borrower_department : "", borrower ? borrower.borrower_email : ""];
    const topInputs = Array.from(modal.querySelectorAll(".form-section .form-group input")).slice(0, 4);
    topInputs.forEach(function (input, index) { input.value = borrowerValues[index]; });
    const sectionTitle = modal.querySelector(".section-title");
    if (sectionTitle) sectionTitle.lastChild.textContent = addingBook ? " ADD BOOK" : " BOOK INFORMATION";
    const next = modal.querySelector(".next-btn");
    const edit = modal.querySelector(".btn-edit");
    if (next) next.textContent = "BORROW";
    if (edit) edit.textContent = addingBook ? "CANCEL" : "EDIT";
    modal.classList.add("active");
  }

  function renderBooks() {
    const table = document.querySelector(".grid-table");
    if (!table) return;
    const header = table.querySelector("thead tr");
    if (header && !header.querySelector("th[data-actions]")) {
      const actionHeader = document.createElement("th");
      actionHeader.dataset.actions = "true";
      actionHeader.textContent = "Actions";
      header.appendChild(actionHeader);
    }
    const tbody = table.querySelector("tbody");
    tbody.innerHTML = books.length ? books.map(function (book) {
      const borrowed = transactions.filter(function (item) { return item.book_id === book.id && item.status === "borrowed"; });
      const borrowerNames = borrowed.map(function (item) { return item.borrower_name; }).join(", ");
      return '<tr data-book-id="' + book.id + '">' +
        '<td class="code">' + escapeHtml(book.barcode) + '</td>' +
        '<td>' + escapeHtml(book.category) + '</td>' +
        '<td class="bold">' + escapeHtml(book.title) + '</td>' +
        '<td>' + escapeHtml(book.author) + '</td>' +
        '<td class="center">' + escapeHtml(book.published_date) + '</td>' +
        '<td class="center">' + book.quantity + '</td>' +
        '<td class="center">' + book.available_quantity + '</td>' +
        '<td class="bold">' + escapeHtml(book.status) + (borrowerNames ? '<br><small>' + escapeHtml(borrowerNames) + '</small>' : '') + '</td>' +
        '<td class="book-actions"><button type="button" data-action="borrow" data-book-id="' + book.id + '">Borrow</button>' +
        (borrowed.length ? '<button type="button" data-action="return" data-book-id="' + book.id + '">Return</button>' : '') +
        '<button type="button" data-action="edit" data-book-id="' + book.id + '">Edit</button>' +
        '<button type="button" data-action="delete" data-book-id="' + book.id + '">Remove</button></td></tr>';
    }).join("") : '<tr><td colspan="9">No books match your search.</td></tr>';
  }

  async function refreshBooks(search) {
    const results = await Promise.all([
      request("/books?q=" + encodeURIComponent(search || "")),
      request("/transactions")
    ]);
    books = results[0].books;
    transactions = results[1].transactions;
    renderBooks();
  }

  async function borrowBook(book) {
    const dueDate = new Date();
    dueDate.setDate(dueDate.getDate() + 14);
    showDialog("Borrow Book", [
      { name: "borrower_school_id", label: "Borrower school ID", required: true },
      { name: "due_date", label: "Due date", type: "date", value: dueDate.toISOString().slice(0, 10), required: true }
    ], book.title, "Confirm Borrow", async function (values) {
      const matches = await request("/borrowers?q=" + encodeURIComponent(values.borrower_school_id.trim()));
      const borrower = matches.borrowers.find(function (item) {
        return item.school_id.toLowerCase() === values.borrower_school_id.trim().toLowerCase();
      });
      if (!borrower) throw new Error("No active student or faculty member has that school ID.");
      await request("/transactions/borrow", {
        method: "POST",
        body: JSON.stringify({ book_id: book.id, borrower_school_id: borrower.school_id, due_date: values.due_date })
      });
      notify("Book borrowed for " + borrower.name + ".");
      await refreshBooks(document.querySelector(".search-box input")?.value || "");
    });
  }

  async function returnBook(book) {
    const borrowed = transactions.filter(function (item) { return item.book_id === book.id && item.status === "borrowed"; });
    if (!borrowed.length) throw new Error("There are no borrowed copies to return.");
    const choices = borrowed.map(function (item) {
      return { value: String(item.id), label: item.borrower_name + " (" + item.borrower_school_id + ")" };
    });
    showDialog("Return Book", [
      { name: "transaction_id", label: "Borrower", type: "select", options: choices, value: choices[0].value, required: true }
    ], book.title, "Confirm Return", async function (values) {
      await request("/transactions/" + Number(values.transaction_id) + "/return", { method: "POST" });
      notify("Book return recorded.");
      await refreshBooks(document.querySelector(".search-box input")?.value || "");
    });
  }

  function bindBooksPage() {
    const table = document.querySelector(".grid-table");
    if (!table) return;
    const search = document.querySelector(".search-box input");
    if (search) search.addEventListener("input", function () {
      refreshBooks(search.value).catch(function (error) { notify(error.message, true); });
    });
    table.querySelector("tbody").addEventListener("click", async function (event) {
      const button = event.target.closest("button[data-action]");
      const row = event.target.closest("tr[data-book-id]");
      if (!row) return;
      const book = books.find(function (item) { return item.id === Number(row.dataset.bookId); });
      if (!book) return;
      try {
        if (!button) return setBookModal(book);
        if (button.dataset.action === "borrow") await borrowBook(book);
        if (button.dataset.action === "return") await returnBook(book);
        if (button.dataset.action === "edit") setBookModal(book);
        if (button.dataset.action === "delete") {
          showDialog("Remove Book", [], book.title, "Remove", async function () {
            await request("/books/" + book.id, { method: "DELETE" });
            notify("Book removed from the catalog.");
            await refreshBooks(search ? search.value : "");
          });
        }
      } catch (error) { notify(error.message, true); }
    });
    const addButton = document.querySelector(".btn-add");
    if (addButton) addButton.addEventListener("click", function () { setBookModal(null); });
    const modal = document.getElementById("bookModal");
    if (!modal) return;
    const close = modal.querySelector(".close-btn");
    if (close) close.addEventListener("click", function () { modal.classList.remove("active"); });
    modal.addEventListener("click", function (event) { if (event.target === modal) modal.classList.remove("active"); });
    const edit = modal.querySelector(".btn-edit");
    if (edit) edit.addEventListener("click", function () {
      if (addingBook) return modal.classList.remove("active");
      Object.keys(bookFields()).forEach(function (key) { if (key !== "status") bookFields()[key].readOnly = false; });
    });
    const save = modal.querySelector(".btn-save");
    if (save) save.addEventListener("click", async function () {
      const fields = bookFields();
      const payload = {};
      ["barcode", "title", "author", "category", "published_date", "quantity"].forEach(function (key) {
        payload[key] = fields[key].value.trim();
      });
      if (!payload.barcode || !payload.title || !payload.author || !payload.category || !payload.quantity) {
        return notify("Complete the book number, title, author, category, and book count.", true);
      }
      try {
        await request(addingBook ? "/books" : "/books/" + activeBook.id, {
          method: addingBook ? "POST" : "PATCH", body: JSON.stringify(payload)
        });
        modal.classList.remove("active");
        notify(addingBook ? "Book added." : "Book details updated.");
        await refreshBooks(document.querySelector(".search-box input")?.value || "");
      } catch (error) { notify(error.message, true); }
    });
    const borrowButton = modal.querySelector(".next-btn");
    if (borrowButton) borrowButton.addEventListener("click", async function () {
      if (!activeBook || addingBook) return notify("Save the book before borrowing it.", true);
      modal.classList.remove("active");
      try { await borrowBook(activeBook); } catch (error) { notify(error.message, true); }
    });
    const coverInput = document.getElementById("bookCoverInput");
    const coverImage = document.getElementById("bookCoverImage");
    const coverFileName = document.getElementById("coverFileName");
    const saveCover = document.getElementById("saveBookCover");
    const resetCover = document.getElementById("resetBookCover");
    if (coverInput) coverInput.addEventListener("change", function () {
      const file = coverInput.files && coverInput.files[0];
      if (!file) return;
      if (coverPreviewUrl) URL.revokeObjectURL(coverPreviewUrl);
      coverPreviewUrl = URL.createObjectURL(file);
      coverImage.src = coverPreviewUrl;
      if (coverFileName) coverFileName.textContent = file.name;
    });
    if (saveCover) saveCover.addEventListener("click", async function () {
      const file = coverInput && coverInput.files && coverInput.files[0];
      if (!activeBook || !file) return notify("Choose an image file first.", true);
      const formData = new FormData();
      formData.append("cover", file);
      try {
        await request("/books/" + activeBook.id + "/cover", { method: "POST", body: formData });
        if (coverPreviewUrl) URL.revokeObjectURL(coverPreviewUrl);
        coverPreviewUrl = null;
        coverInput.value = "";
        if (coverFileName) coverFileName.textContent = "Image saved";
        await refreshBooks(document.querySelector(".search-box input")?.value || "");
        coverImage.src = "/api/books/" + activeBook.id + "/cover?updated=" + Date.now();
        notify("Book image updated.");
      } catch (error) { notify(error.message, true); }
    });
    if (resetCover) resetCover.addEventListener("click", async function () {
      if (!activeBook) return;
      try {
        await request("/books/" + activeBook.id + "/cover", { method: "DELETE" });
        if (coverPreviewUrl) URL.revokeObjectURL(coverPreviewUrl);
        coverPreviewUrl = null;
        coverInput.value = "";
        coverImage.src = "../img/ptc_logo.png";
        if (coverFileName) coverFileName.textContent = "Choose an image file";
        await refreshBooks(document.querySelector(".search-box input")?.value || "");
        notify("Book image reset to the default.");
      } catch (error) { notify(error.message, true); }
    });
    refreshBooks("").catch(function (error) { notify(error.message, true); });
  }

  function showPersonForm(person) {
    const dialog = document.createElement("dialog");
    dialog.className = "api-dialog people-dialog";
    const roles = ["Student", "Faculty", "Staff", "Other"];
    const roleOptions = roles.map(function (role) {
      return '<option value="' + role + '"' + ((person && person.role === role) ? " selected" : "") + ">" + role + "</option>";
    }).join("");
    const statusOptions = ["active", "inactive"].map(function (status) {
      return '<option value="' + status + '"' + ((person && person.status === status) ? " selected" : "") + ">" + status + "</option>";
    }).join("");
    dialog.innerHTML = '<form><h2>' + (person ? "Edit People Information" : "Add People Information") +
      '</h2><div class="dialog-field"><label>School ID<input name="school_id" required maxlength="50" value="' + escapeHtml(person && person.school_id) + '"></label></div>' +
      '<div class="dialog-field"><label>Full Name<input name="name" required maxlength="200" value="' + escapeHtml(person && person.name) + '"></label></div>' +
      '<div class="dialog-field"><label>Role<select name="role" required>' + roleOptions + '</select></label></div>' +
      '<div class="dialog-field"><label>Department<input name="department" maxlength="100" value="' + escapeHtml(person && person.department) + '"></label></div>' +
      '<div class="dialog-field"><label>Contact information<input name="contact" maxlength="80" value="' + escapeHtml(person && person.contact) + '"></label></div>' +
      '<div class="dialog-field"><label>Status<select name="status">' + statusOptions + '</select></label></div>' +
      '<div class="dialog-field"><label>Upload Face Image<input type="file" name="face_image" accept="image/png,image/jpeg,image/gif,image/webp"></label></div>' +
      (person && person.has_face_image ? '<p>Registered face image is stored securely in the main backend.</p>' : "") +
      '<div class="api-dialog-actions"><button type="button" data-cancel>Cancel</button><button type="submit">Save Information</button></div></form>';
    document.body.appendChild(dialog);
    dialog.addEventListener("close", function () { dialog.remove(); });
    dialog.querySelector("[data-cancel]").addEventListener("click", function () { dialog.close(); });
    dialog.querySelector("form").addEventListener("submit", async function (event) {
      event.preventDefault();
      const form = event.currentTarget;
      const values = new FormData(form);
      const image = values.get("face_image");
      const payload = {
        school_id: values.get("school_id").trim(),
        name: values.get("name").trim(),
        role: values.get("role"),
        department: values.get("department").trim(),
        contact: values.get("contact").trim(),
        status: values.get("status")
      };
      try {
        const result = await request(person ? "/people/" + person.id : "/people", {
          method: person ? "PUT" : "POST", body: JSON.stringify(payload)
        });
        const personId = person ? person.id : result.id;
        if (image && image.size) {
          const upload = new FormData();
          upload.append("face_image", image);
          await request("/people/" + personId + "/face", { method: "POST", body: upload });
        }
        dialog.close();
        notify(image && image.size ? "People information and face image saved. Face registration is pending IoT processing." : result.message);
        await loadManagedRecords("people", managedSearchText, managedRoleFilter);
      } catch (error) { notify(error.message, true); }
    });
    dialog.showModal();
  }

  function showSystemUserForm(user) {
    const roles = ["MIS Admin", "Librarian"].map(function (role) { return { value: role, label: role }; });
    const statuses = ["active", "inactive"].map(function (status) { return { value: status, label: status }; });
    const values = user || {};
    showDialog(user ? "Edit System Account" : "Add System User", [
      { name: "school_id", label: "Account ID", value: values.school_id, required: true },
      { name: "name", label: "Full name", value: values.name, required: true },
      { name: "email", label: "Institutional email", type: "email", value: values.email, required: true },
      { name: "role", label: "System role", type: "select", options: roles, value: values.role || "Librarian", required: true },
      { name: "department", label: "Department", value: values.department },
      { name: "status", label: "Account status", type: "select", options: statuses, value: values.status || "active", required: true },
      { name: "password", label: user ? "New password (leave blank to keep current)" : "Password (minimum 8 characters)", type: "password", required: !user }
    ], "Only MIS Admin and Librarian accounts can access the web system.", user ? "Save Changes" : "Add System User", async function (data) {
      await request(user ? "/system-users/" + user.id : "/system-users", {
        method: user ? "PUT" : "POST", body: JSON.stringify(data)
      });
      notify(user ? "System account updated." : "System account added.");
      await loadManagedRecords("system", managedSearchText, managedRoleFilter);
    });
  }

  let managedView = "system";
  let managedSearchText = "";
  let managedRoleFilter = "";

  async function loadManagedRecords(view, searchText, role) {
    const params = new URLSearchParams();
    if (searchText) params.set("q", searchText);
    if (role) params.set("role", role);
    const result = await request("/" + (view === "system" ? "system-users" : "people") + "?" + params.toString());
    managedUsers = view === "system" ? result.users : result.people;
    const body = document.querySelector(".stage tbody");
    const table = document.querySelector(".stage table");
    if (!body || !table) return;
    const head = table.querySelector("thead tr");
    if (view === "system") {
      head.innerHTML = "<th>NAME</th><th>EMAIL</th><th>ROLE</th><th>ACCOUNT STATUS</th><th>CREATED</th><th>LAST LOGIN</th><th class=\"center\">ACTION</th>";
      body.innerHTML = managedUsers.length ? managedUsers.map(function (user) {
        return '<tr data-user-id="' + user.id + '"><td class="bold">' + escapeHtml(user.name) +
          '</td><td>' + escapeHtml(user.email) + '</td><td>' + escapeHtml(user.role) + '</td><td>' + escapeHtml(user.status) +
          '</td><td>' + escapeHtml(user.created_at || "--") + '</td><td>' + escapeHtml(user.last_login_at || "--") +
          '</td><td class="center actions"><button class="btn-icon edit" title="Edit system account" aria-label="Edit system account" data-action="edit">Edit</button>' +
          (user.status === "active" ? '<button class="btn-icon delete" title="Deactivate system account" aria-label="Deactivate system account" data-action="deactivate">Deactivate</button>' : "") +
          '</td></tr>';
      }).join("") : '<tr><td colspan="7">No system accounts found.</td></tr>';
    } else {
      head.innerHTML = "<th>SCHOOL ID</th><th>NAME</th><th>ROLE</th><th>DEPARTMENT</th><th>CONTACT</th><th>STATUS</th><th>FACE RECOGNITION</th><th class=\"center\">ACTION</th>";
      body.innerHTML = managedUsers.length ? managedUsers.map(function (person) {
        return '<tr data-user-id="' + person.id + '"><td class="bold">' + escapeHtml(person.school_id) +
          '</td><td class="bold">' + escapeHtml(person.name) + '</td><td>' + escapeHtml(person.role) +
          '</td><td>' + escapeHtml(person.department) + '</td><td>' + escapeHtml(person.contact) + '</td><td>' + escapeHtml(person.status) +
          '</td><td>' + (person.face_registered ? "Registered" : (person.has_face_image ? "Pending" : "Not registered")) +
          '</td><td class="center actions"><button class="btn-icon edit" title="Edit people information" aria-label="Edit people information" data-action="edit">Edit</button>' +
          (person.status === "active" ? '<button class="btn-icon delete" title="Deactivate person" aria-label="Deactivate person" data-action="deactivate">Deactivate</button>' : "") +
          '</td></tr>';
      }).join("") : '<tr><td colspan="8">No people information found.</td></tr>';
    }
  }

  function bindUsersPage() {
    const tableBody = document.querySelector(".stage tbody");
    if (!tableBody) return;
    const search = document.getElementById("searchInput");
    const add = document.querySelector(".btn-add-user");
    const systemTab = document.getElementById("viewSystemUsers");
    const peopleTab = document.getElementById("viewPeopleInformation");
    const roleFilter = document.getElementById("systemRoleFilter");
    function setView(view) {
      managedView = view;
      managedRoleFilter = view === "system" && roleFilter ? roleFilter.value : "";
      managedSearchText = search ? search.value : "";
      if (systemTab) {
        systemTab.classList.toggle("active", view === "system");
        systemTab.setAttribute("aria-selected", String(view === "system"));
      }
      if (peopleTab) {
        peopleTab.classList.toggle("active", view === "people");
        peopleTab.setAttribute("aria-selected", String(view === "people"));
      }
      if (roleFilter) roleFilter.hidden = view !== "system";
      if (add) add.textContent = view === "system" ? "ADD SYSTEM USER" : "ADD PEOPLE INFORMATION";
      loadManagedRecords(view, managedSearchText, roleFilter ? roleFilter.value : "").catch(function (error) {
        notify(error.message, true);
      });
    }
    if (systemTab) systemTab.addEventListener("click", function () { setView("system"); });
    if (peopleTab) peopleTab.addEventListener("click", function () { setView("people"); });
    if (roleFilter) roleFilter.addEventListener("change", function () {
      managedRoleFilter = roleFilter.value;
      loadManagedRecords("system", managedSearchText, managedRoleFilter).catch(function (error) {
        notify(error.message, true);
      });
    });
    if (search) search.addEventListener("input", function () {
      managedSearchText = search.value;
      loadManagedRecords(managedView, managedSearchText, managedRoleFilter).catch(function (error) {
        notify(error.message, true);
      });
    });
    if (add) add.addEventListener("click", function () {
      if (managedView === "system") showSystemUserForm(null);
      else showPersonForm(null);
    });
    tableBody.addEventListener("click", function (event) {
      const button = event.target.closest("button[data-action]");
      if (!button) return;
      const row = button.closest("tr[data-user-id]");
      const record = managedUsers.find(function (item) { return item.id === Number(row.dataset.userId); });
      if (!record) return;
      if (button.dataset.action === "edit") {
        if (managedView === "system") showSystemUserForm(record);
        else showPersonForm(record);
        return;
      }
      showDialog(managedView === "system" ? "Deactivate System Account" : "Deactivate Person", [],
        record.name + " will no longer be able to sign in or generate attendance records.", "Deactivate", async function () {
          await request((managedView === "system" ? "/system-users/" : "/people/") + record.id, { method: "DELETE" });
          notify(managedView === "system" ? "System account deactivated." : "Person deactivated and attendance closed.");
          await loadManagedRecords(managedView, managedSearchText, managedRoleFilter);
        });
    });
    setView("system");
  }

  function csvCell(value) {
    return '"' + String(value == null ? "" : value).replace(/"/g, '""') + '"';
  }

  function bindReportsPage() {
    const table = document.querySelector(".main table");
    const tbody = table && table.querySelector("tbody");
    if (!table || !tbody) return;
    const dateInputs = document.querySelectorAll(".filter-card input");
    if (dateInputs.length >= 2) {
      dateInputs[0].value = "";
      dateInputs[0].type = "date";
      dateInputs[0].id = "dateFrom";
      dateInputs[1].value = "";
      dateInputs[1].type = "date";
      dateInputs[1].id = "dateTo";
    }
    const filterGrid = document.querySelector(".filter-grid");
    const extraFilters = [
      { id: "attendanceSearch", label: "Search by school ID or name", type: "search", placeholder: "School ID or name" },
      { id: "attendanceRole", label: "Role", type: "select", options: ["Student", "Faculty", "Staff", "Other"] },
      { id: "attendanceDepartment", label: "Department", type: "text", placeholder: "Department or course" },
      { id: "attendanceEvent", label: "Attendance records", type: "select", options: ["all", "time_in", "time_out"], labels: ["All sessions", "Time-in", "Time-out"] }
    ];
    extraFilters.forEach(function (filter) {
      if (document.getElementById(filter.id)) return;
      const field = document.createElement("div");
      field.className = "field filter-field";
      const label = document.createElement("label");
      label.htmlFor = filter.id;
      label.textContent = filter.label;
      let control;
      if (filter.type === "select") {
        control = document.createElement("select");
        const all = document.createElement("option");
        all.value = "";
        all.textContent = filter.id === "attendanceEvent" ? "All sessions" : "All roles";
        control.appendChild(all);
        filter.options.forEach(function (value, index) {
          const option = document.createElement("option");
          option.value = value === "all" ? "all" : value;
          option.textContent = filter.labels ? filter.labels[index] : value;
          control.appendChild(option);
        });
        if (filter.id === "attendanceEvent") control.value = "all";
      } else {
        control = document.createElement("input");
        control.type = filter.type;
        control.placeholder = filter.placeholder;
      }
      control.id = filter.id;
      field.append(label, control);
      if (filterGrid) filterGrid.appendChild(field);
    });
    table.querySelector("thead").innerHTML = "<tr><th>SCHOOL ID</th><th>NAME</th><th>ROLE</th><th>DEPARTMENT</th><th>DATE</th><th>TIME-IN</th><th>TIME-OUT</th><th>STATUS</th></tr>";
    let reportRows = [];
    async function load() {
      const parameters = new URLSearchParams();
      const from = document.getElementById("dateFrom");
      const to = document.getElementById("dateTo");
      const search = document.getElementById("attendanceSearch");
      const role = document.getElementById("attendanceRole");
      const department = document.getElementById("attendanceDepartment");
      const eventType = document.getElementById("attendanceEvent");
      if (from && from.value) parameters.set("from", from.value);
      if (to && to.value) parameters.set("to", to.value);
      if (search && search.value.trim()) parameters.set("q", search.value.trim());
      if (role && role.value) parameters.set("role", role.value);
      if (department && department.value.trim()) parameters.set("department", department.value.trim());
      if (eventType && eventType.value) parameters.set("event", eventType.value);
      const result = await request("/reports/attendance?" + parameters.toString());
      reportRows = result.records;
      tbody.innerHTML = reportRows.length ? reportRows.map(function (item) {
        return "<tr><td>" + escapeHtml(item.school_id) + "</td><td>" + escapeHtml(item.name) +
          "</td><td>" + escapeHtml(item.role) + "</td><td>" + escapeHtml(item.department) +
          "</td><td>" + escapeHtml(item.attendance_date) + "</td><td>" + escapeHtml(item.time_in) +
          "</td><td>" + escapeHtml(item.time_out || "--") + "</td><td>" + escapeHtml(item.status) + "</td></tr>";
      }).join("") : '<tr><td colspan="8">No attendance records in this date range.</td></tr>';
    }
    [document.getElementById("dateFrom"), document.getElementById("dateTo"), document.getElementById("attendanceSearch"),
      document.getElementById("attendanceRole"), document.getElementById("attendanceDepartment"), document.getElementById("attendanceEvent")]
      .filter(Boolean).forEach(function (input) {
        input.addEventListener(input.type === "search" || input.type === "text" ? "input" : "change", function () {
          load().catch(function (error) { notify(error.message, true); });
        });
      });
    const generate = document.querySelector(".btn-generate, .gen-btn");
    if (generate) generate.addEventListener("click", async function () {
      try {
        await load();
        const header = ["School ID", "Name", "Role", "Department", "Date", "Time-in", "Time-out", "Status"];
        const lines = [header.map(csvCell).join(",")];
        reportRows.forEach(function (item) {
          lines.push([item.school_id, item.name, item.role, item.department, item.attendance_date,
            item.time_in, item.time_out, item.status].map(csvCell).join(","));
        });
        const link = document.createElement("a");
        link.href = URL.createObjectURL(new Blob([lines.join("\r\n")], { type: "text/csv;charset=utf-8" }));
        link.download = "smart-library-transactions.csv";
        link.click();
        URL.revokeObjectURL(link.href);
      } catch (error) { notify(error.message, true); }
    });
    load().catch(function (error) { notify(error.message, true); });
  }

  function bindAttendancePage() {
    const table = document.querySelector(".table-container table, .stage table");
    const search = document.querySelector(".search-box input");
    if (!table) return;
    const tbody = table.querySelector("tbody");
    table.querySelector("thead").innerHTML = "<tr><th>SCHOOL ID</th><th>NAME</th><th>ROLE</th><th>DEPARTMENT</th><th>DATE</th><th>TIME-IN</th><th>TIME-OUT</th><th>STATUS</th></tr>";
    async function load() {
      const query = search && search.value.trim() ? "?q=" + encodeURIComponent(search.value.trim()) : "";
      const result = await request("/attendance" + query);
      tbody.innerHTML = result.records.length ? result.records.map(function (item) {
        return "<tr><td>" + escapeHtml(item.school_id) + "</td><td>" + escapeHtml(item.name) +
          "</td><td>" + escapeHtml(item.role) + "</td><td>" + escapeHtml(item.department) +
          "</td><td>" + escapeHtml(item.attendance_date) + "</td><td><span class=\"time-badge\">" +
          escapeHtml(item.time_in) + "</span></td><td>" + (item.time_out ? '<span class="time-badge red">' +
          escapeHtml(item.time_out) + "</span>" : "--") + "</td><td>" + escapeHtml(item.status) + "</td></tr>";
      }).join("") : '<tr><td colspan="8">No attendance records found.</td></tr>';
    }
    if (search) search.addEventListener("input", function () { load().catch(function (error) { notify(error.message, true); }); });
    load().catch(function (error) { notify(error.message, true); });
  }

  async function initializeRolePage() {
    const path = window.location.pathname;
    const expectedRole = path.startsWith("/MIS_ADMIN/") ? "MIS Admin" : "Librarian";
    const result = await request("/auth/me");
    currentUser = result.user;
    if (currentUser.role !== expectedRole) {
      window.location.href = currentUser.role === "MIS Admin" ? "/MIS_ADMIN/dashboard.html" : "/LIBRARIAN/dashboard.html";
      return;
    }
    updateAccountName();
    bindLogout();
    const page = path.split("/").pop();
    if (page === "dashboard.html") {
      const refresh = async function () { renderDashboard(await request("/dashboard")); };
      await refresh();
      window.setInterval(function () { refresh().catch(function (error) { notify(error.message, true); }); }, 15000);
    } else if (page === "time_in_out.html") {
      bindAttendancePage();
    } else if (page === "book_transactions.html") {
      bindBooksPage();
    } else if (page === "reports.html") {
      bindReportsPage();
    } else if (page === "users_management.html") {
      bindUsersPage();
    }
  }

  window.login = login;
  window.togglePassword = togglePassword;
  document.addEventListener("DOMContentLoaded", function () {
    if (document.getElementById("email") && document.querySelector("form")) {
      document.querySelector("form").addEventListener("submit", login);
    }
    if (window.location.pathname.startsWith("/LIBRARIAN/") || window.location.pathname.startsWith("/MIS_ADMIN/")) {
      addInteractiveStyles();
      clearExampleRows(window.location.pathname);
      initializeRolePage().catch(function (error) { notify(error.message, true); });
    }
  });
}());

// WikiApp host: a native window that runs the HTML/JS app in ..\app using WebView2
// (the Edge engine built into Windows). The page talks to this program through
// JSON messages; see app\js\bridge.js for the other side.
//
// Build with host\build.cmd, which uses the C# compiler that ships with Windows.
// This compiler only understands C# 5, so no $"strings", ?. or => members here.

using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace WikiApp
{
    static class Program
    {
        public static readonly string BaseDir = AppDomain.CurrentDomain.BaseDirectory;
        public static readonly string BinDir = Path.Combine(BaseDir, "bin");
        public static readonly string AppDir = Path.Combine(BaseDir, "app");
        // Per-user data, the same however and from wherever the exe is started.
        public static readonly string DataDir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "WikiApp");

        [DllImport("user32.dll")]
        static extern bool SetProcessDpiAwarenessContext(IntPtr value);
        [DllImport("user32.dll")]
        static extern bool SetForegroundWindow(IntPtr hwnd);
        [DllImport("user32.dll")]
        static extern bool ShowWindow(IntPtr hwnd, int command);
        [DllImport("user32.dll")]
        static extern bool IsIconic(IntPtr hwnd);

        [STAThread]
        static void Main(string[] args)
        {
            // The WebView2 DLLs live in bin\ to keep the root folder tidy. UnsafeLoadFrom (rather
            // than LoadFrom) still works when the files came from a downloaded ZIP and Windows
            // has marked them as "from the internet".
            AppDomain.CurrentDomain.AssemblyResolve += (sender, e) =>
            {
                string file = Path.Combine(BinDir, new AssemblyName(e.Name).Name + ".dll");
                return File.Exists(file) ? Assembly.UnsafeLoadFrom(file) : null;
            };
            Run(args);
        }

        // Separate from Main so no WebView2 type is touched before the resolver above exists.
        [MethodImpl(MethodImplOptions.NoInlining)]
        static void Run(string[] args)
        {
            // Per-monitor DPI awareness keeps text sharp on scaled displays.
            try { SetProcessDpiAwarenessContext(new IntPtr(-4)); } catch (EntryPointNotFoundException) { }

            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);

            // One window: starting the app again (taskbar, desktop shortcut, the exe) brings the
            // open window to the front instead of opening a second copy.
            bool firstInstance;
            using (var mutex = new System.Threading.Mutex(true, "WikiApp.SingleInstance." + Environment.UserName, out firstInstance))
            {
                if (!firstInstance && args.Length == 0 && ShowRunningWindow()) return;

                // Optional: WikiApp.exe "C:\notes\team" "C:\notes\personal" adds those folders on start.
                var startupFolders = new List<string>();
                foreach (string arg in args) startupFolders.Add(Path.GetFullPath(arg));
                Application.Run(new MainForm(startupFolders));
            }
        }

        static bool ShowRunningWindow()
        {
            Process self = Process.GetCurrentProcess();
            foreach (Process other in Process.GetProcessesByName(self.ProcessName))
            {
                if (other.Id == self.Id || other.MainWindowHandle == IntPtr.Zero) continue;
                if (IsIconic(other.MainWindowHandle)) ShowWindow(other.MainWindowHandle, 9 /* SW_RESTORE */);
                SetForegroundWindow(other.MainWindowHandle);
                return true;
            }
            return false;
        }
    }

    class MainForm : Form
    {
        const string AppHost = "wikiapp.example";

        readonly WebView2 web = new WebView2();
        CoreWebView2Environment environment;
        readonly JavaScriptSerializer json = new JavaScriptSerializer { MaxJsonLength = int.MaxValue };
        readonly Timer changeDebounce = new Timer { Interval = 400 };
        readonly List<string> startupFolders;
        // One watcher per open folder, keyed by the folder's full path.
        readonly Dictionary<string, FileSystemWatcher> watchers =
            new Dictionary<string, FileSystemWatcher>(StringComparer.OrdinalIgnoreCase);
        readonly HashSet<string> changedRoots = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        public MainForm(List<string> startupFolders)
        {
            this.startupFolders = startupFolders;

            Text = "WikiApp";
            Icon = LoadAppIcon();
            BackColor = Color.FromArgb(30, 30, 30);

            Rectangle area = Screen.PrimaryScreen.WorkingArea;
            StartPosition = FormStartPosition.Manual;
            Size = new Size(area.Width * 8 / 10, area.Height * 8 / 10);
            Location = new Point(area.X + (area.Width - Width) / 2, area.Y + (area.Height - Height) / 2);
            RestoreWindowPlacement();
            FormClosing += (s, e) => SaveWindowPlacement();

            web.Dock = DockStyle.Fill;
            web.DefaultBackgroundColor = BackColor;
            Controls.Add(web);

            changeDebounce.Tick += (s, e) =>
            {
                changeDebounce.Stop();
                foreach (string root in changedRoots)
                {
                    var data = new Dictionary<string, object>();
                    data["root"] = root;
                    PostEvent("vaultChanged", data);
                }
                changedRoots.Clear();
            };
            Load += async (s, e) => { await InitWebView(); };
            FormClosed += (s, e) =>
            {
                foreach (FileSystemWatcher w in watchers.Values) w.Dispose();
                watchers.Clear();
                StopIngest();
            };
        }

        // ---- Window size and position, kept between runs -------------------------------

        static readonly string PlacementFile = Path.Combine(Program.DataDir, "window.txt");

        // window.txt: "x,y,width,height,maximized". Ignored if it would put the window off screen.
        void RestoreWindowPlacement()
        {
            try
            {
                if (!File.Exists(PlacementFile)) return;
                string[] parts = File.ReadAllText(PlacementFile).Trim().Split(',');
                var bounds = new Rectangle(int.Parse(parts[0]), int.Parse(parts[1]), int.Parse(parts[2]), int.Parse(parts[3]));
                if (bounds.Width < 400 || bounds.Height < 300) return;
                bool visible = false;
                foreach (Screen screen in Screen.AllScreens)
                {
                    Rectangle overlap = Rectangle.Intersect(screen.WorkingArea, bounds);
                    if (overlap.Width >= 200 && overlap.Height >= 100) visible = true;
                }
                if (!visible) return;
                Bounds = bounds;
                if (parts.Length > 4 && parts[4] == "1") WindowState = FormWindowState.Maximized;
            }
            catch (Exception) { /* unreadable: use the default size */ }
        }

        void SaveWindowPlacement()
        {
            try
            {
                Rectangle b = WindowState == FormWindowState.Normal ? Bounds : RestoreBounds;
                Directory.CreateDirectory(Program.DataDir);
                File.WriteAllText(PlacementFile, string.Join(",", new[] {
                    b.X.ToString(), b.Y.ToString(), b.Width.ToString(), b.Height.ToString(),
                    WindowState == FormWindowState.Maximized ? "1" : "0" }));
            }
            catch (Exception) { /* not worth failing the close over */ }
        }

        // ---- Settings file -----------------------------------------------------------------
        // The page's settings (open folders, signature, colors, last view...) as one JSON object.
        // See app\js\persist.js.

        static readonly string SettingsFile = Path.Combine(Program.DataDir, "settings.json");

        // Served as /settings.js: "window.__savedSettings = {...};" (null when there's no file yet).
        static string SettingsScript()
        {
            string saved = "null";
            try
            {
                if (File.Exists(SettingsFile))
                {
                    string text = File.ReadAllText(SettingsFile, Encoding.UTF8).Trim();
                    // Only hand over something that is a JSON object.
                    if (text.StartsWith("{") && new JavaScriptSerializer().DeserializeObject(text) is Dictionary<string, object>)
                        saved = text;
                }
            }
            catch (Exception) { /* damaged file: the page keeps its own copy */ }
            return "window.__savedSettings = " + saved + ";";
        }

        // Written to a temporary file first, then swapped in, so a crash can't leave half a file.
        void SaveSettings(object settings)
        {
            if (!(settings is Dictionary<string, object>)) throw new ArgumentException("settings must be an object");
            Directory.CreateDirectory(Program.DataDir);
            string temp = SettingsFile + ".tmp";
            File.WriteAllText(temp, json.Serialize(settings), new UTF8Encoding(false));
            if (File.Exists(SettingsFile)) File.Replace(temp, SettingsFile, null);
            else File.Move(temp, SettingsFile);
        }

        [DllImport("dwmapi.dll")]
        static extern int DwmSetWindowAttribute(IntPtr hwnd, int attribute, ref int value, int size);

        // Dark title bar to match the app (Windows 10 20H1+ / 11; ignored elsewhere).
        protected override void OnHandleCreated(EventArgs e)
        {
            base.OnHandleCreated(e);
            int dark = 1;
            try { DwmSetWindowAttribute(Handle, 20 /* DWMWA_USE_IMMERSIVE_DARK_MODE */, ref dark, sizeof(int)); }
            catch (DllNotFoundException) { }
        }

        static Icon LoadAppIcon()
        {
            using (Stream stream = Assembly.GetExecutingAssembly().GetManifestResourceStream("WikiApp.app.ico"))
            {
                return stream != null ? new Icon(stream) : SystemIcons.Application;
            }
        }

        async Task InitWebView()
        {
            try
            {
                CoreWebView2Environment.SetLoaderDllFolderPath(Program.BinDir);
                environment = await CoreWebView2Environment.CreateAsync(null, Path.Combine(Program.DataDir, "WebView2"));
                await web.EnsureCoreWebView2Async(environment);
            }
            catch (WebView2RuntimeNotFoundException)
            {
                MessageBox.Show(
                    "WikiApp needs the Microsoft Edge WebView2 Runtime, which is missing on this PC.\n\n" +
                    "Download it from https://developer.microsoft.com/microsoft-edge/webview2/",
                    "WikiApp", MessageBoxButtons.OK, MessageBoxIcon.Error);
                Close();
                return;
            }

            CoreWebView2 core = web.CoreWebView2;
            // The app's files are served from ..\app by ServeAppFile, marked "don't cache" so an
            // edited file always shows up on the next reload (F5).
            core.AddWebResourceRequestedFilter("https://" + AppHost + "/*", CoreWebView2WebResourceContext.All);
            core.WebResourceRequested += ServeAppFile;
            core.Settings.IsStatusBarEnabled = false;
            core.DocumentTitleChanged += (s, e) => Text = core.DocumentTitle;

            // The window only ever shows the app itself; any other link opens in the default browser.
            core.NavigationStarting += (s, e) =>
            {
                if (!IsAppUrl(e.Uri))
                {
                    e.Cancel = true;
                    OpenExternal(e.Uri);
                }
            };
            core.NewWindowRequested += (s, e) =>
            {
                e.Handled = true;
                OpenExternal(e.Uri);
            };
            core.WebMessageReceived += OnWebMessage;
            core.Navigate("https://" + AppHost + "/index.html");
        }

        static readonly Dictionary<string, string> MimeTypes = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            { ".html", "text/html; charset=utf-8" }, { ".js", "text/javascript; charset=utf-8" },
            { ".mjs", "text/javascript; charset=utf-8" }, { ".css", "text/css; charset=utf-8" },
            { ".json", "application/json; charset=utf-8" }, { ".svg", "image/svg+xml" },
            { ".png", "image/png" }, { ".jpg", "image/jpeg" }, { ".gif", "image/gif" },
            { ".ico", "image/x-icon" }, { ".woff2", "font/woff2" }, { ".txt", "text/plain; charset=utf-8" },
        };

        void ServeAppFile(object sender, CoreWebView2WebResourceRequestedEventArgs e)
        {
            string relative = Uri.UnescapeDataString(new Uri(e.Request.Uri).AbsolutePath).TrimStart('/').Replace('/', '\\');
            if (relative.Equals("settings.js", StringComparison.OrdinalIgnoreCase))
            {
                e.Response = environment.CreateWebResourceResponse(
                    new MemoryStream(new UTF8Encoding(false).GetBytes(SettingsScript())), 200, "OK",
                    "Content-Type: text/javascript; charset=utf-8\r\nCache-Control: no-store");
                return;
            }
            string appDir = Path.GetFullPath(Program.AppDir).TrimEnd('\\') + "\\";
            string file = Path.GetFullPath(Path.Combine(appDir, relative));
            if (!file.StartsWith(appDir, StringComparison.OrdinalIgnoreCase) || !File.Exists(file))
            {
                e.Response = environment.CreateWebResourceResponse(null, 404, "Not Found", "");
                return;
            }
            string type;
            if (!MimeTypes.TryGetValue(Path.GetExtension(file), out type)) type = "application/octet-stream";
            e.Response = environment.CreateWebResourceResponse(
                new MemoryStream(File.ReadAllBytes(file)), 200, "OK",
                "Content-Type: " + type + "\r\nCache-Control: no-store");
        }

        static bool IsAppUrl(string uri)
        {
            return uri.StartsWith("https://" + AppHost + "/", StringComparison.OrdinalIgnoreCase);
        }

        static void OpenExternal(string uri)
        {
            if (uri == null) return;
            if (uri.StartsWith("http://", StringComparison.OrdinalIgnoreCase) ||
                uri.StartsWith("https://", StringComparison.OrdinalIgnoreCase) ||
                uri.StartsWith("mailto:", StringComparison.OrdinalIgnoreCase))
            {
                Process.Start(uri);
            }
        }

        // ---- Messages from the page ----------------------------------------------------
        // Request:  { id, cmd, args }      Reply: { id, ok, result | error }
        // Events pushed to the page:       { event, data }

        async void OnWebMessage(object sender, CoreWebView2WebMessageReceivedEventArgs e)
        {
            Dictionary<string, object> msg;
            try { msg = json.Deserialize<Dictionary<string, object>>(e.WebMessageAsJson); }
            catch (ArgumentException) { return; }
            if (msg == null) return;

            object args;
            msg.TryGetValue("args", out args);
            var reply = new Dictionary<string, object>();
            reply["id"] = msg.ContainsKey("id") ? msg["id"] : null;
            try
            {
                reply["result"] = await Dispatch(msg.ContainsKey("cmd") ? msg["cmd"] as string : null,
                    args as Dictionary<string, object> ?? new Dictionary<string, object>());
                reply["ok"] = true;
            }
            catch (Exception ex)
            {
                reply["ok"] = false;
                reply["error"] = ex.Message;
            }
            if (web.CoreWebView2 != null) web.CoreWebView2.PostWebMessageAsJson(json.Serialize(reply));
        }

        async Task<object> Dispatch(string cmd, Dictionary<string, object> args)
        {
            switch (cmd)
            {
                case "getStartupFolders":
                    return startupFolders;

                case "pickFolder":
                    return FolderPicker.Show(Handle, "Choose a wiki folder");

                // watch: false is used by the Add folder window to preview a folder before adding it.
                case "scanVault":
                    string path = StringArg(args, "path");
                    Dictionary<string, object> vault = await Task.Run(() => Vault.Scan(path));
                    object watch;
                    if (!args.TryGetValue("watch", out watch) || !false.Equals(watch))
                        StartWatching((string)vault["root"]);
                    return vault;

                case "unwatchFolder":
                    StopWatching(Path.GetFullPath(StringArg(args, "path")).TrimEnd('\\'));
                    return null;

                // Replace `expect` (lines starting at 0-based line `start`) with `replace`.
                // Fails without writing if those lines changed on disk since the page read them.
                case "editLines":
                    NoteFiles.EditLines(StringArg(args, "root"), StringArg(args, "path"),
                        Convert.ToInt32(args["start"]), StringListArg(args, "expect"), StringListArg(args, "replace"));
                    return null;

                // Append lines to a note, creating it (starting with `header`) if it doesn't exist.
                case "appendLines":
                    NoteFiles.AppendLines(StringArg(args, "root"), StringArg(args, "path"),
                        StringListArg(args, "lines"), StringListArg(args, "header"));
                    return null;

                // The text of a file inside an open folder (scripts linked from notes). Read-only.
                case "readText":
                    return Vault.ReadText(StringArg(args, "root"), StringArg(args, "path"));

                // The page's settings, to %LOCALAPPDATA%\WikiApp\settings.json.
                case "saveSettings":
                    object settings;
                    args.TryGetValue("settings", out settings);
                    SaveSettings(settings);
                    return null;

                // Create a new note with these lines. Fails if the file already exists.
                case "createNote":
                    NoteFiles.Create(StringArg(args, "root"), StringArg(args, "path"), StringListArg(args, "lines"));
                    return null;

                case "openExternal":
                    OpenExternal(StringArg(args, "url"));
                    return null;

                // ---- Ingest (see ingest\DESIGN.md) ----

                // Whether ingest is set up and running, the shipped agent prompt, the user's own
                // notes for the agent, and the saved Ingest state (cards waiting for review).
                case "ingestInfo":
                    return Ingest.Info(IsIngestRunning(), ingestRunId);

                case "saveIngestState":
                    Ingest.WriteData(Ingest.StateFile, StringArg(args, "state"));
                    return null;

                case "saveIngestNotes":
                    Ingest.WriteData(Ingest.UserNotesFile, StringArg(args, "text"));
                    return null;

                // Starts ingest\run.py on a job from the page. Progress comes back as "ingest" events.
                case "startIngest":
                    object job;
                    args.TryGetValue("job", out job);
                    return StartIngest(job as Dictionary<string, object>);

                // feedback: { cards: [{ card, text }], accepted: [ids], rejected: [ids] }
                case "reviseIngestCards":
                    object feedback;
                    args.TryGetValue("feedback", out feedback);
                    ReviseIngestCards(StringArg(args, "runId"), feedback as Dictionary<string, object>);
                    return null;

                case "cancelIngest":
                    StopIngest();
                    return null;

                // The models Claude Code offers (ingest\models.py; takes a few seconds, costs nothing).
                case "listIngestModels":
                    string modelsJson = await Task.Run(() => Ingest.Models());
                    return json.DeserializeObject(modelsJson);

                // Runs setup.py in a console window, so the user sees it install.
                case "runIngestSetup":
                    string python = File.Exists(Ingest.Python) ? "\"" + Ingest.Python + "\"" : "python";
                    Process.Start(new ProcessStartInfo("cmd.exe", "/k \"" + python + " \"" + Ingest.SetupScript + "\"\"") { UseShellExecute = true });
                    return null;

                // Past runs, newest first: [{ runId, transcript (the text of transcript.json, or null) }].
                case "listIngestRuns":
                    return Ingest.ListRuns(30);

                case "openIngestRun":
                    string runDir = Ingest.RunDir(StringArg(args, "runId"));
                    if (Directory.Exists(runDir)) Process.Start("explorer.exe", "\"" + runDir + "\"");
                    return null;

                default:
                    throw new InvalidOperationException("Unknown command: " + cmd);
            }
        }

        static string StringArg(Dictionary<string, object> args, string name)
        {
            object value;
            if (!args.TryGetValue(name, out value) || !(value is string))
                throw new ArgumentException("Missing argument: " + name);
            return (string)value;
        }

        static List<string> StringListArg(Dictionary<string, object> args, string name)
        {
            object value;
            var list = new List<string>();
            if (!args.TryGetValue(name, out value) || value == null) return list;
            if (!(value is IEnumerable) || value is string) throw new ArgumentException("Expected a list: " + name);
            foreach (object item in (IEnumerable)value) list.Add(Convert.ToString(item));
            return list;
        }

        void PostEvent(string name, object data)
        {
            if (web.CoreWebView2 == null) return;
            var msg = new Dictionary<string, object>();
            msg["event"] = name;
            msg["data"] = data;
            web.CoreWebView2.PostWebMessageAsJson(json.Serialize(msg));
        }

        // ---- Ingest runs ---------------------------------------------------------------------
        // One run at a time: ingest\run.py in the app's .venv Python, with no console window.
        // Each line it prints (a JSON object) is passed to the page as an "ingest" event.

        Process ingestProcess;
        string ingestRunId;

        bool IsIngestRunning()
        {
            return ingestProcess != null && !ingestProcess.HasExited;
        }

        string StartIngest(Dictionary<string, object> job)
        {
            if (job == null) throw new ArgumentException("Missing argument: job");
            if (IsIngestRunning()) throw new InvalidOperationException("An ingest run is already going.");
            if (!File.Exists(Ingest.Python)) throw new InvalidOperationException("Ingest isn't set up yet. Run the setup first.");

            string runId = DateTime.Now.ToString("yyyy-MM-dd_HHmmss");
            string runDir = Ingest.RunDir(runId);
            Directory.CreateDirectory(runDir);
            job["runId"] = runId;
            job["userNotes"] = File.Exists(Ingest.UserNotesFile) ? File.ReadAllText(Ingest.UserNotesFile) : "";
            string jobFile = Path.Combine(runDir, "job.json");
            File.WriteAllText(jobFile, json.Serialize(job), new UTF8Encoding(false));
            LaunchRun(runId, "\"" + jobFile + "\"");
            return runId;
        }

        // A feedback round: the same run continues (run.py resumes its Claude session) with the
        // user's feedback on some cards. Progress comes back as "ingest" events, like a run.
        void ReviseIngestCards(string runId, Dictionary<string, object> feedback)
        {
            if (feedback == null || !feedback.ContainsKey("cards")) throw new ArgumentException("Missing argument: feedback");
            if (IsIngestRunning()) throw new InvalidOperationException("Claude is still working. Wait for it to finish.");
            if (!File.Exists(Ingest.Python)) throw new InvalidOperationException("Ingest isn't set up yet. Run the setup first.");
            string runDir = Ingest.RunDir(runId);
            string jobFile = Path.Combine(runDir, "job.json");
            if (!File.Exists(jobFile) || !File.Exists(Path.Combine(runDir, "session.json")))
                throw new InvalidOperationException("This run's folder is gone, so Claude can't continue it.");
            int n = Directory.GetFiles(runDir, "feedback-*.json").Length + 1;
            string feedbackFile = Path.Combine(runDir, "feedback-" + n + ".json");
            File.WriteAllText(feedbackFile, json.Serialize(feedback), new UTF8Encoding(false));
            LaunchRun(runId, "\"" + jobFile + "\" --feedback \"" + feedbackFile + "\"");
        }

        void LaunchRun(string runId, string arguments)
        {
            var info = new ProcessStartInfo(Ingest.Python, "-X utf8 \"" + Ingest.RunScript + "\" " + arguments);
            info.WorkingDirectory = Ingest.CodeDir;
            info.UseShellExecute = false;
            info.CreateNoWindow = true;
            info.RedirectStandardOutput = true;
            info.RedirectStandardError = true;
            info.StandardOutputEncoding = Encoding.UTF8;
            info.StandardErrorEncoding = Encoding.UTF8;

            var process = new Process { StartInfo = info, EnableRaisingEvents = true };
            var errors = new StringBuilder();
            process.OutputDataReceived += (s, e) =>
            {
                if (string.IsNullOrEmpty(e.Data)) return;
                string line = e.Data;
                try { BeginInvoke((Action)(() => PostEvent("ingest", line))); }
                catch (InvalidOperationException) { } // window is closing
            };
            process.ErrorDataReceived += (s, e) =>
            {
                if (e.Data == null) return;
                lock (errors) { if (errors.Length < 8000) errors.AppendLine(e.Data); }
            };
            process.Exited += (s, e) =>
            {
                // WaitForExit() also waits for the last output lines to be read.
                Task.Run(() =>
                {
                    process.WaitForExit();
                    var data = new Dictionary<string, object>();
                    data["runId"] = runId;
                    data["code"] = process.ExitCode;
                    lock (errors) { data["errors"] = errors.ToString(); }
                    try { BeginInvoke((Action)(() => PostEvent("ingestExit", data))); }
                    catch (InvalidOperationException) { }
                });
            };
            process.Start();
            process.BeginOutputReadLine();
            process.BeginErrorReadLine();
            ingestProcess = process;
            ingestRunId = runId;
        }

        // Stops the run and everything it started (Claude Code runs as a child process).
        void StopIngest()
        {
            if (!IsIngestRunning()) return;
            try
            {
                var kill = new ProcessStartInfo("taskkill", "/T /F /PID " + ingestProcess.Id);
                kill.CreateNoWindow = true;
                kill.UseShellExecute = false;
                Process.Start(kill).WaitForExit(5000);
            }
            catch (Exception) { }
        }

        // ---- Watching the open folders for changes ----------------------------------------

        void StartWatching(string root)
        {
            if (watchers.ContainsKey(root)) return;
            var watcher = new FileSystemWatcher(root);
            watcher.IncludeSubdirectories = true;
            watcher.InternalBufferSize = 64 * 1024;
            watcher.NotifyFilter = NotifyFilters.FileName | NotifyFilters.DirectoryName | NotifyFilters.LastWrite;
            watcher.Changed += OnFileEvent;
            watcher.Created += OnFileEvent;
            watcher.Deleted += OnFileEvent;
            watcher.Renamed += OnFileEvent;
            watcher.EnableRaisingEvents = true;
            watchers[root] = watcher;
        }

        void StopWatching(string root)
        {
            FileSystemWatcher watcher;
            if (!watchers.TryGetValue(root, out watcher)) return;
            watcher.Dispose();
            watchers.Remove(root);
        }

        void OnFileEvent(object sender, FileSystemEventArgs e)
        {
            if (Vault.IsInHiddenFolder(e.Name)) return;
            string root = ((FileSystemWatcher)sender).Path;
            // Many events arrive at once (e.g. an editor saving), so wait for a quiet moment.
            try
            {
                BeginInvoke((Action)(() =>
                {
                    changedRoots.Add(root);
                    changeDebounce.Stop();
                    changeDebounce.Start();
                }));
            }
            catch (InvalidOperationException) { } // window is closing
        }
    }

    // The only code that writes files. It only touches .md files inside a folder the page
    // names, keeps the file's line endings and BOM, and refuses to edit lines that changed.
    static class NoteFiles
    {
        public static void EditLines(string root, string relative, int start, List<string> expect, List<string> replace)
        {
            string file = ResolveNote(root, relative);
            bool bom;
            string newline;
            List<string> lines = Read(file, out bom, out newline);

            bool matches = start >= 0 && start + expect.Count <= lines.Count;
            for (int i = 0; matches && i < expect.Count; i++) matches = lines[start + i] == expect[i];
            if (!matches) throw new InvalidOperationException("The note changed on disk. It has been reloaded; try again.");

            lines.RemoveRange(start, expect.Count);
            lines.InsertRange(start, replace);
            Write(file, lines, bom, newline);
        }

        public static void AppendLines(string root, string relative, List<string> add, List<string> header)
        {
            string file = ResolveNote(root, relative);
            if (!File.Exists(file))
            {
                Directory.CreateDirectory(Path.GetDirectoryName(file));
                var created = new List<string>(header);
                created.AddRange(add);
                created.Add("");
                Write(file, created, false, "\r\n");
                return;
            }
            bool bom;
            string newline;
            List<string> lines = Read(file, out bom, out newline);
            // Keep exactly one trailing empty line (= the file ends with a newline).
            while (lines.Count > 0 && lines[lines.Count - 1] == "") lines.RemoveAt(lines.Count - 1);
            lines.AddRange(add);
            lines.Add("");
            Write(file, lines, bom, newline);
        }

        public static void Create(string root, string relative, List<string> lines)
        {
            string file = ResolveNote(root, relative);
            if (File.Exists(file)) throw new InvalidOperationException("A note with that name already exists.");
            Directory.CreateDirectory(Path.GetDirectoryName(file));
            Write(file, lines, false, "\r\n");
        }

        static string ResolveNote(string root, string relative)
        {
            string rootFull = Path.GetFullPath(root).TrimEnd('\\') + "\\";
            string full = Path.GetFullPath(Path.Combine(rootFull, relative.Replace('/', '\\')));
            if (!full.StartsWith(rootFull, StringComparison.OrdinalIgnoreCase))
                throw new UnauthorizedAccessException("That file is outside the folder.");
            string ext = Path.GetExtension(full).ToLowerInvariant();
            if (ext != ".md" && ext != ".markdown")
                throw new UnauthorizedAccessException("Only Markdown notes can be edited.");
            return full;
        }

        static List<string> Read(string file, out bool bom, out string newline)
        {
            byte[] bytes = File.ReadAllBytes(file);
            bom = bytes.Length >= 3 && bytes[0] == 0xEF && bytes[1] == 0xBB && bytes[2] == 0xBF;
            int skip = bom ? 3 : 0;
            string text;
            try
            {
                // Strict: writing back a note that isn't UTF-8 would replace every character that didn't decode.
                text = new UTF8Encoding(false, true).GetString(bytes, skip, bytes.Length - skip);
            }
            catch (DecoderFallbackException)
            {
                throw new InvalidOperationException("This note isn't saved as UTF-8 text, so the app won't change it. " +
                    "Re-save it as UTF-8 in another editor to edit it here.");
            }
            newline = text.Contains("\r\n") ? "\r\n" : "\n";
            var lines = new List<string>(text.Split('\n'));
            for (int i = 0; i < lines.Count; i++) lines[i] = lines[i].TrimEnd('\r');
            return lines;
        }

        // Writes a hidden temp file next to the note, then swaps it in, so a full disk or a crash
        // mid-write leaves the old note whole instead of an empty or cut-off one.
        static void Write(string file, List<string> lines, bool bom, string newline)
        {
            string temp = Path.Combine(Path.GetDirectoryName(file), "." + Path.GetFileName(file) + "." + Guid.NewGuid().ToString("N") + ".tmp");
            try
            {
                File.WriteAllText(temp, string.Join(newline, lines), new UTF8Encoding(bom));
                if (File.Exists(file)) File.Replace(temp, file, null);
                else File.Move(temp, file);
            }
            finally
            {
                if (File.Exists(temp)) File.Delete(temp);
            }
        }
    }

    static class Vault
    {
        const long MaxNoteBytes = 5 * 1024 * 1024;
        static readonly DateTime Epoch = new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc);

        // Returns { root, name, folders: [relPath], files: [{ path, size, mtime, content? }] }.
        // Paths are relative to root with forward slashes; only notes include their text.
        public static Dictionary<string, object> Scan(string root)
        {
            root = Path.GetFullPath(root).TrimEnd('\\');
            if (!Directory.Exists(root)) throw new DirectoryNotFoundException("Folder not found: " + root);

            var folders = new List<string>();
            var files = new List<object>();
            Walk(root, root, folders, files);

            var result = new Dictionary<string, object>();
            result["root"] = root;
            result["name"] = Path.GetFileName(root);
            result["folders"] = folders;
            result["files"] = files;
            return result;
        }

        static void Walk(string root, string dir, List<string> folders, List<object> files)
        {
            foreach (string sub in Directory.GetDirectories(dir))
            {
                if (IsHidden(sub)) continue;
                folders.Add(Relative(root, sub));
                try { Walk(root, sub, folders, files); }
                catch (UnauthorizedAccessException) { }
            }
            foreach (string file in Directory.GetFiles(dir))
            {
                if (IsHidden(file)) continue;
                var info = new FileInfo(file);
                var entry = new Dictionary<string, object>();
                entry["path"] = Relative(root, file);
                entry["size"] = info.Length;
                entry["mtime"] = (long)(info.LastWriteTimeUtc - Epoch).TotalMilliseconds;
                if (IsNote(file) && info.Length <= MaxNoteBytes)
                {
                    try { entry["content"] = File.ReadAllText(file); }
                    catch (IOException) { }
                }
                files.Add(entry);
            }
        }

        const long MaxTextBytes = 2 * 1024 * 1024;

        // A file's text, for showing it. Only files inside `root`, up to 2 MB.
        public static string ReadText(string root, string relative)
        {
            string rootFull = Path.GetFullPath(root).TrimEnd('\\') + "\\";
            string full = Path.GetFullPath(Path.Combine(rootFull, relative.Replace('/', '\\')));
            if (!full.StartsWith(rootFull, StringComparison.OrdinalIgnoreCase))
                throw new UnauthorizedAccessException("That file is outside the folder.");
            if (new FileInfo(full).Length > MaxTextBytes) throw new InvalidOperationException("The file is too large to show (over 2 MB).");
            return File.ReadAllText(full);
        }

        static bool IsNote(string path)
        {
            string ext = Path.GetExtension(path).ToLowerInvariant();
            return ext == ".md" || ext == ".markdown";
        }

        // Dot-folders (.git, .obsidian, ...) and hidden files are skipped.
        static bool IsHidden(string path)
        {
            if (Path.GetFileName(path).StartsWith(".")) return true;
            try { return (File.GetAttributes(path) & FileAttributes.Hidden) != 0; }
            catch (IOException) { return true; }
        }

        public static bool IsInHiddenFolder(string relativePath)
        {
            foreach (string part in relativePath.Split('\\', '/'))
                if (part.StartsWith(".")) return true;
            return false;
        }

        static string Relative(string root, string path)
        {
            return path.Substring(root.Length + 1).Replace('\\', '/');
        }
    }

    // Ingest's files: the Python scripts in ingest\ next to the exe, the user's data in
    // %LOCALAPPDATA%\WikiApp\ingest (cards waiting for review, notes for the agent), and one folder
    // per run in %TEMP%\WikiApp\ingest-runs. Runs live in Temp because the Microsoft Store build of
    // Python can't see other programs' folders in %LOCALAPPDATA%; Windows may clear old ones.
    static class Ingest
    {
        public static readonly string CodeDir = Path.Combine(Program.BaseDir, "ingest");
        // The app's Python environment, shared with host\wikiapp.py and made by setup.py.
        public static readonly string Python = Path.Combine(Program.BaseDir, ".venv", "Scripts", "python.exe");
        public static readonly string RunScript = Path.Combine(CodeDir, "run.py");
        public static readonly string ModelsScript = Path.Combine(CodeDir, "models.py");
        public static readonly string SetupScript = Path.Combine(Program.BaseDir, "setup.py");
        public static readonly string ShippedPrompt = Path.Combine(CodeDir, "agent-prompt.md");
        public static readonly string DataDir = Path.Combine(Program.DataDir, "ingest");
        public static readonly string StateFile = Path.Combine(DataDir, "pending.json");
        public static readonly string UserNotesFile = Path.Combine(DataDir, "user-notes.md");

        public static string RunDir(string runId)
        {
            foreach (char c in runId)
                if (!char.IsLetterOrDigit(c) && c != '-' && c != '_') throw new ArgumentException("Bad run id.");
            return Path.Combine(Path.GetTempPath(), "WikiApp", "ingest-runs", runId);
        }

        public static Dictionary<string, object> Info(bool running, string runId)
        {
            var info = new Dictionary<string, object>();
            info["ready"] = File.Exists(Python);
            info["running"] = running;
            info["runId"] = running ? runId : null;
            info["prompt"] = ReadOrNull(ShippedPrompt);
            info["userNotes"] = ReadOrNull(UserNotesFile) ?? "";
            info["state"] = ReadOrNull(StateFile);
            info["dataDir"] = DataDir;
            return info;
        }

        // models.py's output: a JSON list of { id, name, description }.
        public static string Models()
        {
            if (!File.Exists(Python)) throw new InvalidOperationException("Ingest isn't set up yet. Run the setup first.");
            var info = new ProcessStartInfo(Python, "-X utf8 \"" + ModelsScript + "\"");
            info.WorkingDirectory = CodeDir;
            info.UseShellExecute = false;
            info.CreateNoWindow = true;
            info.RedirectStandardOutput = true;
            info.RedirectStandardError = true;
            info.StandardOutputEncoding = Encoding.UTF8;
            info.StandardErrorEncoding = Encoding.UTF8;
            using (var process = Process.Start(info))
            {
                Task<string> errors = process.StandardError.ReadToEndAsync();
                string output = process.StandardOutput.ReadToEnd();
                if (!process.WaitForExit(90000))
                {
                    try { process.Kill(); } catch (InvalidOperationException) { }
                    throw new InvalidOperationException("Claude Code didn't answer in time.");
                }
                if (process.ExitCode != 0)
                {
                    string[] lines = errors.Result.Trim().Split('\n');
                    throw new InvalidOperationException(lines[lines.Length - 1].Trim().Length > 0 ? lines[lines.Length - 1].Trim() : "models.py failed.");
                }
                return output;
            }
        }

        public static List<object> ListRuns(int max)
        {
            var runs = new List<object>();
            string root = Path.GetDirectoryName(RunDir("x"));
            if (!Directory.Exists(root)) return runs;
            var dirs = new List<string>(Directory.GetDirectories(root));
            dirs.Sort(StringComparer.OrdinalIgnoreCase);
            dirs.Reverse(); // run ids are timestamps, so this is newest first
            foreach (string dir in dirs)
            {
                if (runs.Count >= max) break;
                var run = new Dictionary<string, object>();
                run["runId"] = Path.GetFileName(dir);
                run["transcript"] = ReadOrNull(Path.Combine(dir, "transcript.json"));
                runs.Add(run);
            }
            return runs;
        }

        static string ReadOrNull(string file)
        {
            return File.Exists(file) ? File.ReadAllText(file) : null;
        }

        // Written to a temporary file first, so a crash mid-write never leaves half a file.
        public static void WriteData(string file, string text)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(file));
            string temp = file + ".tmp";
            File.WriteAllText(temp, text, new UTF8Encoding(false));
            if (File.Exists(file)) File.Replace(temp, file, null);
            else File.Move(temp, file);
        }
    }

    // The modern Windows "Select folder" dialog (WinForms only has the old tree-style one).
    static class FolderPicker
    {
        const uint FOS_PICKFOLDERS = 0x20;
        const uint FOS_FORCEFILESYSTEM = 0x40;
        const uint SIGDN_FILESYSPATH = 0x80058000;
        const int ERROR_CANCELLED = unchecked((int)0x800704C7);

        public static string Show(IntPtr owner, string title)
        {
            var dialog = (IFileDialog)new FileOpenDialogCom();
            try
            {
                uint options;
                dialog.GetOptions(out options);
                dialog.SetOptions(options | FOS_PICKFOLDERS | FOS_FORCEFILESYSTEM);
                dialog.SetTitle(title);

                int hr = dialog.Show(owner);
                if (hr == ERROR_CANCELLED) return null;
                if (hr != 0) Marshal.ThrowExceptionForHR(hr);

                IShellItem item;
                dialog.GetResult(out item);
                string path;
                item.GetDisplayName(SIGDN_FILESYSPATH, out path);
                Marshal.ReleaseComObject(item);
                return path;
            }
            finally
            {
                Marshal.ReleaseComObject(dialog);
            }
        }

        [ComImport, Guid("DC1C5A9C-E88A-4dde-A5A1-60F82A20AEF7")]
        class FileOpenDialogCom { }

        // Methods are declared in vtable order; ones after GetResult are never called and omitted.
        [ComImport, Guid("42f85136-db7e-439c-85f1-e4075d135fc8"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        interface IFileDialog
        {
            [PreserveSig] int Show(IntPtr parent);
            void SetFileTypes(uint count, IntPtr filterSpec);
            void SetFileTypeIndex(uint index);
            void GetFileTypeIndex(out uint index);
            void Advise(IntPtr events, out uint cookie);
            void Unadvise(uint cookie);
            void SetOptions(uint options);
            void GetOptions(out uint options);
            void SetDefaultFolder(IShellItem item);
            void SetFolder(IShellItem item);
            void GetFolder(out IShellItem item);
            void GetCurrentSelection(out IShellItem item);
            void SetFileName([MarshalAs(UnmanagedType.LPWStr)] string name);
            void GetFileName([MarshalAs(UnmanagedType.LPWStr)] out string name);
            void SetTitle([MarshalAs(UnmanagedType.LPWStr)] string title);
            void SetOkButtonLabel([MarshalAs(UnmanagedType.LPWStr)] string text);
            void SetFileNameLabel([MarshalAs(UnmanagedType.LPWStr)] string label);
            void GetResult(out IShellItem item);
        }

        [ComImport, Guid("43826D1E-E718-42EE-BC55-A1E261C37BFE"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        interface IShellItem
        {
            void BindToHandler(IntPtr bindContext, ref Guid handler, ref Guid iid, out IntPtr result);
            void GetParent(out IShellItem parent);
            void GetDisplayName(uint type, [MarshalAs(UnmanagedType.LPWStr)] out string name);
        }
    }
}

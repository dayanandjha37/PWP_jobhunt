# **PWP JobHunt — Setup**

## **1\. Create the project folder**

Create a new folder anywhere on your computer.

Open that folder in **VS Code**.

Open the VS Code terminal.

---

## **2\. Clone the project**

Run:

git clone https://github.com/perryvegehan/PWP\_jobhunt.git

Then enter the project:

cd PWP\_jobhunt  
---

## **3\. Check Python**

Run:

python \--version

You should have **Python 3.10 or newer**.

---

## **4\. Create the virtual environment**

Run:

python \-m venv .venv

Activate it:

### **Windows**

.\\.venv\\Scripts\\Activate.ps1

You should see:

(.venv)

at the beginning of your terminal.

> If PowerShell says that script execution is disabled, run:

Set-ExecutionPolicy \-Scope Process \-ExecutionPolicy Bypass

Then activate again:

.\\.venv\\Scripts\\Activate.ps1  
---

## **5\. Install the required packages**

Run:

python \-m pip install \-r requirements.txt  
---

## **6\. Test the installation**

Run:

python \-m jobhunt run \--mock \--scorer keyword

If you see a mock job search and a generated digest, your installation is working. ✅

---

# **🔑 7\. Get your Gemini API key**

Go to:

[Google AI Studio — API Keys](https://aistudio.google.com/apikey?utm_source=chatgpt.com)

Sign in with your Google account.

Create an API key and copy it.

**Never share your API key with anyone.**

---

# **📧 8\. Set up email**

If you want the job digest to be sent to your email:

Go to:

[Google App Passwords](https://myaccount.google.com/apppasswords?utm_source=chatgpt.com)

Generate an **App Password**.

Google will give you a 16-character password.

**This is NOT your normal Gmail password.**

Keep the App Password somewhere safe.

---

# **⚙️ 9\. Create your `.env` file**

Run:

copy .env.example .env

Open `.env`.

You need to fill in:

GEMINI\_API\_KEY=YOUR\_GEMINI\_API\_KEY

and your email details:

SMTP\_USER=your-email@gmail.com  
SMTP\_PASS=YOUR\_GMAIL\_APP\_PASSWORD  
MAIL\_TO=your-email@gmail.com

The rest can remain as it is.

**Never upload or share your `.env` file.**

---

# **📄 10\. Add your resume**

Put your resume PDF inside the `PWP_jobhunt` folder.

For example:

PWP\_jobhunt/  
├── resume.pdf  
├── companies.yaml  
├── config.yaml  
└── ...  
---

# **🤖 11\. Generate your profile**

Run:

python \-m jobhunt profile \--resume resume.pdf

This creates:

profile.json

Open `profile.json` and **check that the AI understood your resume correctly**.

Pay particular attention to:

* Experience  
* Skills  
* Target roles  
* Domains  
* Projects

---

# **🏢 12\. Choose your companies**

Open:

companies.yaml

This file tells the tool **which companies to search**.

Instead of manually finding companies and ATS slugs, upload your resume to ChatGPT or Claude and use this prompt:

> I have uploaded my resume.

> Based on my **skills, experience, projects, education, and likely job level**, find the **15 companies I should target for software/tech jobs**.

> Important requirements:

> * Search the web and use the company's **current official careers/job board**.  
> * Only include companies whose jobs are hosted on one of these ATS platforms:  
>   * Greenhouse  
>   * Lever  
>   * Ashby  
> * Verify the ATS and slug. **Do not guess.**  
> * Prefer companies where my background is a realistic match, not just famous companies.  
> * Consider the technologies, domains, experience level, and type of work shown in my resume.  
> * Exclude companies that don't use Greenhouse, Lever, or Ashby.  
> * If you cannot verify the ATS/slug, don't include that company.  
> * Give me exactly **15 companies**, if 15 suitable supported companies can be found.

> For each company, return **only this format**:

> \- {ats: greenhouse, slug: company-slug, name: Company Name}

> Use `lever` or `ashby` when appropriate.

> At the end, return all 15 lines together in one YAML block so I can directly copy them into my `companies.yaml` file.

> Do not give me explanations, rankings, descriptions, or URLs. I only want the 15 YAML lines.

Then copy the 15 lines into:

companies.yaml

under:

companies:

### **Important**

**Don't guess ATS slugs.**

If ChatGPT/Claude cannot verify a company, don't add it.

---

# **⚙️ 13\. Customize `config.yaml`**

Open:

config.yaml

This controls **what kind of jobs you're looking for**.

The main things you may want to change are:

include\_titles:

→ Jobs you **want**

exclude\_titles:

→ Jobs you **don't want**

locations:

→ Locations you are willing to work in

allow\_remote:

→ Whether remote jobs are allowed

max\_age\_days:

→ How old a job posting can be

score\_threshold:

→ Minimum AI match score

max\_per\_digest:

→ Maximum number of jobs included in the final digest

### **Simple example**

locations:  
  \- bangalore  
  \- bengaluru  
  \- india

allow\_remote: true

max\_age\_days: 30

score\_threshold: 7.0

max\_per\_digest: 5

**You usually don't need to change the other settings.**

---

# **🧪 14\. First real test**

Before your first real run, reset `seen.json` so you start with a fresh job history.

Open:

seen.json

and change its contents to:

{}

Then run:

python \-m jobhunt run \--limit 10

### **What does `--limit 10` mean?**

It limits the number of jobs processed during this test.

**It does NOT send an email.**

The digest will be created here:

out/digest.html

Open it and check the results.

You should see:

* Recommended jobs  
* Match information  
* Job details  
* Application links  
* Generated application material

---

# **📧 15\. Test email**

Once you're happy with the digest, run:

python \-m jobhunt run \--send

This will run the job search and send the digest to the email address you put in `.env`.

Check your inbox.

---

# **🌅 Every morning**

You **do not need to repeat the setup**.

Every morning:

### **1\. Open the project in VS Code**

### **2\. Activate the virtual environment**

.\\.venv\\Scripts\\Activate.ps1

### **3\. Run:**

python \-m jobhunt run \--send

That's it.

The tool keeps track of jobs it has already seen using:

seen.json

So **do not reset `seen.json` every morning**.

Only reset it when you intentionally want to start your job search history from scratch.


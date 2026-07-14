# 🎨 Syllabus-to-Calendar Frontend - User Guide

## 🚀 Quick Start

### Open the App
1. **Windows**: Double-click `index.html` in File Explorer
2. **Mac/Linux**: Open `index.html` with your browser
3. **URL**: `file:///C:/Users/venkat/project007/syltocal/Mark-Calender/index.html`

---

## 📋 4-Step Process

### ✅ Step 1: Upload
- **Drag & Drop**: Drag your syllabus file onto the upload zone
- **Click Upload**: Click "Choose File" button to browse
- **Supported Formats**: PDF, TXT, MD (max 20 MB)

### ⏳ Step 2: Processing (Auto-Advances)
Watch the progress bar as your file is processed:
- 0-25%: Reading file
- 25-50%: Extracting text from PDF
- 50-75%: Sending to AI for analysis
- 75-100%: Validating extracted data

Real-time status messages show exactly what's happening.

### ✏️ Step 3: Review & Edit
**This is where you have full control!**

#### Edit Events:
- Click any field to modify:
  - **Course Name**: Update course title
  - **Task/Assignment Name**: Fix event titles
  - **Due Date**: Change using date picker
  - **Due Time**: Adjust deadline time
  - **Description**: Add notes or context

#### Manage Events:
- **🗑️ Delete**: Remove any incorrect event
- **➕ Add**: Create new events manually
- **📊 Stats**: See total events and course name in real-time

#### Quick Tips:
- All edits are instant (no save button needed)
- Add missing assignments using the "Add New Event" button
- Delete duplicate or incorrect extractions
- Modify times if AI extracted them incorrectly

### ⬇️ Step 4: Download
- Click **"Download Calendar File"** button
- File saves as `syllabus_[YEAR]_events.ics`
- Instructions shown for importing into:
  - Google Calendar
  - Outlook
  - Apple Calendar
  - Any calendar app that supports .ics

---

## 🎨 Design Features

| Feature | Benefit |
|---------|---------|
| **Gradient Background** | Modern, clean aesthetic |
| **Glass Morphism Cards** | Professional frosted glass effect |
| **Step Indicators** | Always know where you are in the process |
| **Progress Bar** | Visual feedback during processing |
| **Responsive Design** | Works on desktop, tablet, and mobile |
| **Smooth Animations** | Delightful transitions between steps |
| **Live Stats** | Real-time event counter and course name |

---

## 💡 Pro Tips

1. **Large Syllabi**: For long syllabi (30+ pages), processing may take 10-15 seconds
2. **Editing Multiple Events**: Use Tab key to jump between fields
3. **Date Format**: Dates auto-format to YYYY-MM-DD (e.g., 2024-09-15)
4. **Time Format**: Use 24-hour format (e.g., 14:30 = 2:30 PM)
5. **Add Events**: Don't see an assignment? Use "Add New Event" to create it manually
6. **Re-process**: Click "Process Another Syllabus" to start over

---

## 📱 Mobile Usage

The interface is fully responsive:
- ✓ Upload works on mobile
- ✓ Swipe to navigate between steps
- ✓ Touch-friendly buttons and inputs
- ✓ Optimized for smaller screens

---

## 🐛 Troubleshooting

### "Upload Failed" Error
- Check file size (must be < 20 MB)
- Ensure file is .pdf, .txt, or .md
- File should contain readable text (not just scanned images)

### "Processing Stuck"
- Wait 60 seconds (free tier has 15 requests/minute limit)
- Refresh the page
- Try a smaller file first

### Events Not Extracted Correctly
- Use the Review step to manually edit or delete incorrect events
- Add missing events using "Add New Event" button
- Recheck the syllabus for unusual formatting

### Can't Import to Calendar
- Ensure file downloaded successfully
- Check that your calendar app supports .ics import
- Try dragging the .ics file directly into your calendar

---

## 📞 Need Help?

- Check the import guide on the Download step
- Review the event details in the Edit step
- Make sure all events have valid dates and times

---

**Made with ❤️ for students | Powered by Google Gemini AI**

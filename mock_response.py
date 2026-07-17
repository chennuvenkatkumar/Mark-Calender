"""Mock Gemini response for testing the full extraction pipeline."""

# This is the expected JSON output from Gemini for the sample_syllabus.txt
MOCK_GEMINI_RESPONSE = """[
  {
    "course_name": "Introduction to Python Programming",
    "task_name": "Assignment 1: Hello World and Variables",
    "due_date": "2024-09-15",
    "due_time": "23:59",
    "description": "Basic Python variables and syntax"
  },
  {
    "course_name": "Introduction to Python Programming",
    "task_name": "Quiz 1 on Python syntax",
    "due_date": "2024-09-22",
    "due_time": "17:00",
    "description": "Python syntax evaluation"
  },
  {
    "course_name": "Introduction to Python Programming",
    "task_name": "Assignment 2: Build a Calculator",
    "due_date": "2024-10-01",
    "due_time": "23:59",
    "description": "Function and module implementation"
  },
  {
    "course_name": "Introduction to Python Programming",
    "task_name": "Midterm Project Proposal",
    "due_date": "2024-10-08",
    "due_time": "15:00",
    "description": "Project proposal submission"
  },
  {
    "course_name": "Introduction to Python Programming",
    "task_name": "Assignment 3: Create a Class",
    "due_date": "2024-10-20",
    "due_time": "23:59",
    "description": "Object-oriented programming implementation"
  },
  {
    "course_name": "Introduction to Python Programming",
    "task_name": "Lab Practical Exam",
    "due_date": "2024-10-27",
    "due_time": "14:00",
    "description": "Practical coding examination"
  },
  {
    "course_name": "Introduction to Python Programming",
    "task_name": "Assignment 4: List and Dictionary Operations",
    "due_date": "2024-11-10",
    "due_time": "23:59",
    "description": "Data structures practice"
  },
  {
    "course_name": "Introduction to Python Programming",
    "task_name": "Code Review Submission",
    "due_date": "2024-11-15",
    "due_time": "16:00",
    "description": "Code quality and best practices review"
  },
  {
    "course_name": "Introduction to Python Programming",
    "task_name": "Assignment 5: API Integration Project",
    "due_date": "2024-11-25",
    "due_time": "23:59",
    "description": "Working with external APIs"
  },
  {
    "course_name": "Introduction to Python Programming",
    "task_name": "Final Project Presentation",
    "due_date": "2024-12-03",
    "due_time": "13:00",
    "description": "Capstone project presentation"
  },
  {
    "course_name": "Introduction to Python Programming",
    "task_name": "Final Exam",
    "due_date": "2024-12-15",
    "due_time": "10:00",
    "description": "Comprehensive final assessment"
  },
  {
    "course_name": "Introduction to Python Programming",
    "task_name": "Assignment 6: Capstone Project",
    "due_date": "2024-12-20",
    "due_time": "23:59",
    "description": "Advanced Python project showcase"
  }
]"""

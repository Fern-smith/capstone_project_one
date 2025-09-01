#Project Proposal: Recipe Sharing Web Application 


1. Project Goal : The goal of this project is to create a user-friendly web application where users can share, discover, and save recipes. Users can upload their own recipes with images, search and filter recipes based on ingredients or cuisine types, view nutritional information, and interact socially through likes and comments.
 
2.Target Demographic
    2.1 Home cooks looking for inspiration 
    2.2 Aspiring chefs seeking to share their creations
    2.3 Health-conscious users wanting to find recipes with specific nutrition profiles(e.g. Low carb, vegan)
    2.4 Age group: 18-50 years old.
    2.5 Device focus: Mobile-responsive and desktop-friendly.

3. Data Source and API
    3.1 User-generated content (primary data)
    3.2 Spoonacular API: 	Recipe suggestions, Nutritional information , Ingredient analysis       	

4. Database Schema(Rough Draft) 
    4.1 Users:  id, username, email, password_hash, created_at. 
    4.2 Recipes: id,user_id(FK), title, ingredients(text), instructions (text), image_url, created_at
    4.3 Comments: id, user_id(FK), recipe_id(FK), comment_text, created_at
    4.4 Favourites -> id, user_id(FK), recipe_id(FK)
    4.5 Categories -> id, name
    4.6 Relationships: 
        4.6.1 One user -> many recipes
        4.6.2 One recipe -> many comments
        4.6.3 One user -> many favorites

5. Key Functionality
    5.1 User authentication (sign up, login, logout)
    5.2 Submit a recipe (title, ingredients, instructions, image)
    5.3 Edit/delete own recipes
    5.4 View all recipes (searchable and filterable)
    5.5 Like (favorite) recipes
    5.6 Comment on recipes
    5.7 Save favorite recipes to profile.

6. User Flow 
    6.1 Landing page -> view featured or random recipes 
    6.2 Sign up/login -> create account 
    6.3 Dashboard -> upload new recipes, view saved recipes
    6.4 Recipe browsing -> search by keyword or filter by category 
    6.5 Recipe page -> view recipe details, nutrition, edit/delete recipes 
    6.6 Logout.

7. Potential Issues
    7.1 API rate limits : Spoonacular has daily limits; caching may be needed. 
    7.2 Image uploads: File size handling and storage space concerns.
    7.3 Security: Password hashing (using bcrypt), SQL injection prevention (using SQLAlchemy ORM), CSRF protection for forms
    7.4 Nutrition API delay: External API calls could slow down page load; solution: async loading or background tasks. 

8. tretch Features (Beyond CRUD) 
    8.1 Tagging system (e.g. gluten-free, vegetarian)
    8.2 Meal planning feature (weekly meal plans from favorite recipes)
    8.3 Upload short recipe videos
    8.4 Follow other users and see a feed of their new recipes
    8.5 Ratings system(1-5 stars)
    8.6 dmin dashboard (for moderating reported content)

![alt text](<images/Log In.png>)
![alt text](<images/Edit Recipe.png>)
![alt text](<images/Create Recipe.png>)
![alt text](<images/Recipe Detail.png>)


